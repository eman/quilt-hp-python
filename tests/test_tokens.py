"""Tests for FileStore token persistence."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from quilt_hp.cli.store import FileStore
from quilt_hp.tokens import CachedTokens


@pytest.mark.asyncio
async def test_save_and_load(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    tokens = CachedTokens(id_token="id", refresh_token="rf", expires_at=9999999999.0)
    with patch.object(store, "_token_path", return_value=path):
        await store.save("user@test.com", tokens)
        loaded = await store.load("user@test.com")
    assert loaded is not None
    assert loaded.id_token == "id"
    assert loaded.refresh_token == "rf"


@pytest.mark.asyncio
async def test_load_missing_email(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    with patch.object(store, "_token_path", return_value=path):
        assert await store.load("nobody@test.com") is None


@pytest.mark.asyncio
async def test_file_permissions(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    tokens = CachedTokens(id_token="x", refresh_token="y", expires_at=0.0)
    with patch.object(store, "_token_path", return_value=path):
        await store.save("user@test.com", tokens)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_multiple_accounts(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    t1 = CachedTokens(id_token="a", refresh_token="r1", expires_at=1.0)
    t2 = CachedTokens(id_token="b", refresh_token="r2", expires_at=2.0)
    with patch.object(store, "_token_path", return_value=path):
        await store.save("a@test.com", t1)
        await store.save("b@test.com", t2)
        first = await store.load("a@test.com")
        second = await store.load("b@test.com")
    assert first is not None
    assert second is not None
    assert first.id_token == "a"
    assert second.id_token == "b"


@pytest.mark.asyncio
async def test_clear_tokens(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    tokens = CachedTokens(id_token="x", refresh_token="y", expires_at=0.0)
    with patch.object(store, "_token_path", return_value=path):
        await store.save("user@test.com", tokens)
        store.clear_tokens("user@test.com")
        assert await store.load("user@test.com") is None


@pytest.mark.asyncio
async def test_list_emails(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    with patch.object(store, "_token_path", return_value=path):
        await store.save(
            "a@test.com",
            CachedTokens(id_token="a", refresh_token="", expires_at=0.0),
        )
        await store.save(
            "b@test.com",
            CachedTokens(id_token="b", refresh_token="", expires_at=0.0),
        )
        assert sorted(store.list_emails()) == ["a@test.com", "b@test.com"]


@pytest.mark.asyncio
async def test_load_invalid_json_recovers_with_backup(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    path.write_text("{not-json")
    with patch.object(store, "_token_path", return_value=path):
        # Corruption is quarantined (renamed to a .corrupt-* backup) and the
        # store starts empty — worst case is one re-login, never a hard lock.
        assert await store.load("user@test.com") is None
    _assert_corrupt_backup(tmp_path, path)


def _assert_corrupt_backup(tmp_path: Path, path: Path) -> None:
    assert not path.exists()
    backups = list(tmp_path.glob("tokens.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{not-json"


def test_is_expired() -> None:
    assert CachedTokens(id_token="x", refresh_token="y", expires_at=0.0).is_expired
    assert not CachedTokens(id_token="x", refresh_token="y", expires_at=9999999999.0).is_expired
