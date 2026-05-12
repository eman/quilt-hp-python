"""Token persistence store for CLI/TUI authentication state.

Token persistence remains intentionally separate from general user
preferences. ``FileStore`` implements the core ``TokenStore`` protocol
and can be passed directly to ``QuiltClient(token_store=store)``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from quilt_hp._paths import app_config_dir
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CachedTokens

logger = logging.getLogger(__name__)


def _warn_if_permission_error(action: str, path: Path, exc: OSError) -> None:
    if isinstance(exc, PermissionError):
        logger.warning("Permission denied while %s token file %s", action, path)


class FileStore:
    """Filesystem-backed token persistence."""

    # ------------------------------------------------------------------ tokens

    def _token_path(self) -> Path:
        return app_config_dir() / "tokens.json"

    def _atomic_write(self, payload: dict[str, object]) -> None:
        path = self._token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            # Open with O_CREAT|O_WRONLY|O_TRUNC and mode 0o600 so the file
            # is never world-readable, even transiently before chmod.
            fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(payload, indent=2))
            os.replace(tmp, path)
            os.chmod(path, 0o600)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    async def load(self, email: str) -> CachedTokens | None:
        """TokenStore.load — return cached tokens for *email* or None."""
        return await asyncio.to_thread(self._load_sync, email)

    def _load_sync(self, email: str) -> CachedTokens | None:
        path = self._token_path()
        logger.debug("Loading token file %s", path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            _warn_if_permission_error("reading", path, exc)
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
        logger.debug("Saving token file %s", path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            data = {}
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            _warn_if_permission_error("reading", path, exc)
            raise QuiltAuthError("Failed to read token store.") from exc
        data[email] = asdict(tokens)
        try:
            self._atomic_write(data)
        except OSError as exc:
            _warn_if_permission_error("writing", path, exc)
            raise QuiltAuthError("Failed to persist token store.") from exc

    def clear_tokens(self, email: str) -> None:
        """Remove cached tokens for *email*."""
        path = self._token_path()
        logger.debug("Loading token file %s", path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            _warn_if_permission_error("reading", path, exc)
            raise QuiltAuthError("Failed to read token store.") from exc

        data.pop(email, None)
        logger.debug("Saving token file %s", path)
        try:
            self._atomic_write(data)
        except OSError as exc:
            _warn_if_permission_error("writing", path, exc)
            raise QuiltAuthError("Failed to persist token store.") from exc

    def list_emails(self) -> list[str]:
        """All email addresses that have cached tokens."""
        path = self._token_path()
        logger.debug("Loading token file %s", path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as exc:
            raise QuiltAuthError("Token store contains invalid JSON.") from exc
        except OSError as exc:
            _warn_if_permission_error("reading", path, exc)
            raise QuiltAuthError("Failed to read token store.") from exc
        return [k for k in data if isinstance(k, str)]
