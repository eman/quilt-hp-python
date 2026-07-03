"""Token persistence store for CLI/TUI authentication state.

Token persistence remains intentionally separate from general user
preferences. ``FileStore`` implements the core ``TokenStore`` protocol
and can be passed directly to ``QuiltClient(token_store=store)``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from quilt_hp._paths import app_config_dir
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CachedTokens

if TYPE_CHECKING:
    from collections.abc import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _warn_if_permission_error(action: str, path: Path, exc: OSError) -> None:
    if isinstance(exc, PermissionError):
        logger.warning("Permission denied while %s token file %s", action, path)


class FileStore:
    """Filesystem-backed token persistence."""

    # ------------------------------------------------------------------ tokens

    def _token_path(self) -> Path:
        return app_config_dir() / "tokens.json"

    @contextlib.contextmanager
    def _file_lock(self) -> Iterator[None]:
        """Advisory inter-process lock around read-modify-write cycles.

        Uses ``fcntl.flock`` on a sibling ``.lock`` file (Linux/macOS). On
        platforms or filesystems without flock support this degrades to a
        no-op — the atomic-replace write still prevents torn files.
        """
        if fcntl is None:
            yield
            return
        lock_path = self._token_path().with_name("tokens.json.lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
        except OSError:
            yield
            return
        try:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _recover_corruption(self, reason: str) -> None:
        """Move a corrupt token file aside so the store can start empty.

        Worst case is one re-login instead of a permanent QuiltAuthError.
        """
        path = self._token_path()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        # uuid suffix: timestamps have 1s resolution, so concurrent or
        # repeated recoveries must not collide on the backup name (a failed
        # replace would leave the corrupt file in place forever).
        backup = path.with_name(f"{path.name}.corrupt-{timestamp}-{uuid4().hex[:8]}-{reason}")
        logger.warning(
            "Token store %s is corrupt (%s); moving it to %s and starting empty",
            path,
            reason,
            backup,
        )
        with contextlib.suppress(OSError):
            path.replace(backup)

    def _read_all(self) -> dict[str, Any]:
        """Read the full token file, recovering from corruption."""
        path = self._token_path()
        logger.debug("Loading token file %s", path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            self._recover_corruption("invalid-json")
            return {}
        except OSError as exc:
            _warn_if_permission_error("reading", path, exc)
            raise QuiltAuthError("Failed to read token store.") from exc
        if not isinstance(data, dict):
            self._recover_corruption("invalid-shape")
            return {}
        return data

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
                f.flush()
                os.fsync(f.fileno())
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
        data = self._read_all()
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
        with self._file_lock():
            data = self._read_all()
            data[email] = asdict(tokens)
            logger.debug("Saving token file %s", path)
            try:
                self._atomic_write(data)
            except OSError as exc:
                _warn_if_permission_error("writing", path, exc)
                raise QuiltAuthError("Failed to persist token store.") from exc

    def clear_tokens(self, email: str) -> None:
        """Remove cached tokens for *email*."""
        path = self._token_path()
        with self._file_lock():
            data = self._read_all()
            if email not in data:
                return
            data.pop(email, None)
            logger.debug("Saving token file %s", path)
            try:
                self._atomic_write(data)
            except OSError as exc:
                _warn_if_permission_error("writing", path, exc)
                raise QuiltAuthError("Failed to persist token store.") from exc

    def list_emails(self) -> list[str]:
        """All email addresses that have cached tokens."""
        return [k for k in self._read_all() if isinstance(k, str)]
