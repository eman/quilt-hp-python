from __future__ import annotations

import json
from pathlib import Path

import pytest

from quilt_hp import auth
from quilt_hp.cli.settings import SettingsStore
from quilt_hp.cli.store import FileStore
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CachedTokens, RefreshFailureAction, TokenRefreshContext


def _corrupt_backups(directory: Path) -> list[Path]:
    """Sync helper so async tests avoid direct Path.glob (ASYNC240)."""
    return sorted(directory.glob("tokens.json.corrupt-*"))


class _RaisePolicy:
    def on_refresh_failure(
        self, _context: TokenRefreshContext, _error: Exception
    ) -> RefreshFailureAction:
        return RefreshFailureAction.RAISE


@pytest.mark.asyncio
async def test_authenticate_falls_back_to_otp_after_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Store:
        async def load(self, _email: str) -> CachedTokens | None:
            return CachedTokens(id_token="expired", refresh_token="rf", expires_at=0.0)

        async def save(self, _email: str, _tokens: CachedTokens) -> None:
            return None

    async def _bad_refresh(_token: str) -> dict[str, str | int]:
        raise QuiltAuthError("refresh failed")

    async def _otp(_email: str, _cb: auth.OtpCallback) -> dict[str, str | int]:
        return {"IdToken": "otp-token", "RefreshToken": "rf2", "ExpiresIn": 1200}

    monkeypatch.setattr(auth, "_do_refresh", _bad_refresh)
    monkeypatch.setattr(auth, "_do_otp_login", _otp)

    token = await auth.authenticate(
        "user@example.com", otp_callback=lambda _email: "123456", token_store=_Store()
    )
    assert token == "otp-token"


@pytest.mark.asyncio
async def test_authenticate_refresh_missing_id_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Store:
        async def load(self, _email: str) -> CachedTokens | None:
            return CachedTokens(id_token="expired", refresh_token="rf", expires_at=0.0)

        async def save(self, _email: str, _tokens: CachedTokens) -> None:
            return None

    async def _missing_id(_token: str) -> dict[str, str | int]:
        return {"ExpiresIn": 50}

    monkeypatch.setattr(auth, "_do_refresh", _missing_id)

    with pytest.raises(QuiltAuthError, match="IdToken"):
        await auth.authenticate(
            "user@example.com", token_store=_Store(), refresh_policy=_RaisePolicy()
        )


@pytest.mark.asyncio
async def test_filestore_malformed_entry_and_clear_json_errors(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"user@example.com": "not-an-object"}))

    with (
        pytest.raises(QuiltAuthError, match="Malformed token entry"),
        pytest.MonkeyPatch.context() as m,
    ):
        m.setattr(store, "_token_path", lambda: path)
        await store.load("user@example.com")

    # Corrupt JSON no longer raises: the file is quarantined and the store
    # starts empty, so the worst case is one re-login.
    path.write_text("{bad-json")
    with pytest.MonkeyPatch.context() as m:
        m.setattr(store, "_token_path", lambda: path)
        store.clear_tokens("user@example.com")

    assert not path.exists()
    backups = _corrupt_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].read_text() == "{bad-json"


async def test_filestore_recovers_from_corrupt_file_on_load(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    path.write_text("{bad-json")

    with pytest.MonkeyPatch.context() as m:
        m.setattr(store, "_token_path", lambda: path)
        assert await store.load("user@example.com") is None
        # File was quarantined; a subsequent save works and round-trips.
        tokens = CachedTokens(
            id_token="id",
            refresh_token="ref",
            expires_at=9999999999.0,
        )
        await store.save("user@example.com", tokens)
        loaded = await store.load("user@example.com")

    assert loaded is not None
    assert loaded.refresh_token == "ref"
    assert _corrupt_backups(tmp_path)


async def test_filestore_recovers_from_non_dict_payload(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(["not", "a", "dict"]))

    with pytest.MonkeyPatch.context() as m:
        m.setattr(store, "_token_path", lambda: path)
        assert await store.load("user@example.com") is None

    assert _corrupt_backups(tmp_path)


def test_settings_store_corruption_and_schema_edges(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    path.write_text(json.dumps(["not-a-dict"]))
    assert store.load().email is None

    path.write_text(json.dumps({"schema_version": 99, "preferences": {}}))
    assert store.load().home is None

    path.write_text(json.dumps({"schema_version": 1, "preferences": ["oops"]}))
    assert store.load().dark is None

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "preferences": {
                    "email": 1,
                    "home": 2,
                    "use_fahrenheit": "yes",
                    "dark": "no",
                },
            }
        )
    )
    settings = store.load()
    assert settings.email is None
    assert settings.home is None
    assert settings.use_fahrenheit is False
    assert settings.dark is None
