"""Tests for FileStore token persistence."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

from quilt_hp.cli.store import FileStore
from quilt_hp.tokens import CachedTokens


def _store(tmp_path: Path) -> FileStore:
    """Return a FileStore whose files land in tmp_path."""
    s = FileStore()
    with patch.object(s, "_token_path", return_value=tmp_path / "tokens.json"):
        return s


def test_save_and_load(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    tokens = CachedTokens(id_token="id", refresh_token="rf", expires_at=9999999999.0)
    with patch.object(store, "_token_path", return_value=path):
        store.save("user@test.com", tokens)
        loaded = store.load("user@test.com")
    assert loaded is not None
    assert loaded.id_token == "id"
    assert loaded.refresh_token == "rf"


def test_load_missing_email(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    with patch.object(store, "_token_path", return_value=path):
        assert store.load("nobody@test.com") is None


def test_file_permissions(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    tokens = CachedTokens(id_token="x", refresh_token="y", expires_at=0.0)
    with patch.object(store, "_token_path", return_value=path):
        store.save("user@test.com", tokens)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_multiple_accounts(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    t1 = CachedTokens(id_token="a", refresh_token="r1", expires_at=1.0)
    t2 = CachedTokens(id_token="b", refresh_token="r2", expires_at=2.0)
    with patch.object(store, "_token_path", return_value=path):
        store.save("a@test.com", t1)
        store.save("b@test.com", t2)
        assert store.load("a@test.com").id_token == "a"  # type: ignore[union-attr]
        assert store.load("b@test.com").id_token == "b"  # type: ignore[union-attr]


def test_clear_tokens(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    tokens = CachedTokens(id_token="x", refresh_token="y", expires_at=0.0)
    with patch.object(store, "_token_path", return_value=path):
        store.save("user@test.com", tokens)
        store.clear_tokens("user@test.com")
        assert store.load("user@test.com") is None


def test_list_emails(tmp_path: Path) -> None:
    store = FileStore()
    path = tmp_path / "tokens.json"
    with patch.object(store, "_token_path", return_value=path):
        store.save("a@test.com", CachedTokens(id_token="a", refresh_token="", expires_at=0.0))
        store.save("b@test.com", CachedTokens(id_token="b", refresh_token="", expires_at=0.0))
        assert sorted(store.list_emails()) == ["a@test.com", "b@test.com"]


def test_is_expired() -> None:
    assert CachedTokens(id_token="x", refresh_token="y", expires_at=0.0).is_expired
    assert not CachedTokens(id_token="x", refresh_token="y", expires_at=9999999999.0).is_expired
