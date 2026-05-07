"""Token persistence store for CLI/TUI authentication state.

Token persistence remains intentionally separate from general user
preferences. ``FileStore`` implements the core ``TokenStore`` protocol
and can be passed directly to ``QuiltClient(token_store=store)``.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from quilt_hp._paths import app_config_dir
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CachedTokens


class FileStore:
    """Filesystem-backed token persistence."""

    # ------------------------------------------------------------------ tokens

    def _token_path(self) -> Path:
        return app_config_dir() / "tokens.json"

    async def load(self, email: str) -> CachedTokens | None:
        """TokenStore.load — return cached tokens for *email* or None."""
        return await asyncio.to_thread(self._load_sync, email)

    def _load_sync(self, email: str) -> CachedTokens | None:
        try:
            data = json.loads(self._token_path().read_text())
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            raise QuiltAuthError("Failed to read token store.") from exc

        try:
            entry = data[email]
            return CachedTokens(
                id_token=entry["id_token"],
                refresh_token=entry["refresh_token"],
                expires_at=entry["expires_at"],
            )
        except KeyError:
            return None
        except (TypeError, ValueError) as exc:
            raise QuiltAuthError(f"Malformed token entry for {email!r}.") from exc

    async def save(self, email: str, tokens: CachedTokens) -> None:
        """TokenStore.save — persist tokens for *email*."""
        await asyncio.to_thread(self._save_sync, email, tokens)

    def _save_sync(self, email: str, tokens: CachedTokens) -> None:
        path = self._token_path()
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            data = {}
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            raise QuiltAuthError("Failed to read token store.") from exc
        data[email] = asdict(tokens)
        try:
            path.write_text(json.dumps(data, indent=2))
            os.chmod(path, 0o600)
        except OSError as exc:
            raise QuiltAuthError("Failed to persist token store.") from exc

    def clear_tokens(self, email: str) -> None:
        """Remove cached tokens for *email*."""
        path = self._token_path()
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            raise QuiltAuthError("Failed to read token store.") from exc

        data.pop(email, None)
        try:
            path.write_text(json.dumps(data, indent=2))
            os.chmod(path, 0o600)
        except OSError as exc:
            raise QuiltAuthError("Failed to persist token store.") from exc

    def list_emails(self) -> list[str]:
        """All email addresses that have cached tokens."""
        try:
            data = json.loads(self._token_path().read_text())
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            raise QuiltAuthError("Failed to read token store.") from exc
        return [k for k in data if isinstance(k, str)]
