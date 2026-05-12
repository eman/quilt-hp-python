from __future__ import annotations

import json
from pathlib import Path

import pytest

from quilt_hp import auth
from quilt_hp.cli.settings import SettingsStore
from quilt_hp.cli.store import FileStore
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CachedTokens, RefreshFailureAction, TokenRefreshContext


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

    path.write_text("{bad-json")
    with (
        pytest.raises(QuiltAuthError, match="invalid JSON"),
        pytest.MonkeyPatch.context() as m,
    ):
        m.setattr(store, "_token_path", lambda: path)
        store.clear_tokens("user@example.com")


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
