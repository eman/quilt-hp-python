"""Persistent CLI/TUI store — tokens and user preferences.

All state lives in two files under the platform config directory
(e.g. ``~/Library/Application Support/quilt-hp/`` on macOS,
``~/.config/quilt-hp/`` on Linux):

  tokens.json    Cognito tokens, keyed by email (chmod 600)
  settings.json  User preferences: email, home, use_fahrenheit, dark

``FileStore`` implements the core ``TokenStore`` protocol so it can be
passed directly to ``QuiltClient(token_store=store)``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from quilt_hp._paths import app_config_dir
from quilt_hp.tokens import CachedTokens


class FileStore:
    """Single object for all CLI persistent state."""

    # ------------------------------------------------------------------ tokens

    def _token_path(self) -> Path:
        return app_config_dir() / "tokens.json"

    def load(self, email: str) -> CachedTokens | None:
        """TokenStore.load — return cached tokens for *email* or None."""
        try:
            data = json.loads(self._token_path().read_text())
            e = data[email]
            return CachedTokens(
                id_token=e["id_token"],
                refresh_token=e["refresh_token"],
                expires_at=e["expires_at"],
            )
        except Exception:
            return None

    def save(self, email: str, tokens: CachedTokens) -> None:
        """TokenStore.save — persist tokens for *email*."""
        path = self._token_path()
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
        data[email] = asdict(tokens)
        path.write_text(json.dumps(data, indent=2))
        os.chmod(path, 0o600)

    def clear_tokens(self, email: str) -> None:
        """Remove cached tokens for *email*."""
        path = self._token_path()
        try:
            data = json.loads(path.read_text())
            data.pop(email, None)
            path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def list_emails(self) -> list[str]:
        """All email addresses that have cached tokens."""
        try:
            data = json.loads(self._token_path().read_text())
            return [k for k in data if isinstance(k, str)]
        except Exception:
            return []

    # --------------------------------------------------------------- settings

    def _settings_path(self) -> Path:
        return app_config_dir() / "settings.json"

    def load_settings(self) -> dict[str, Any]:
        """Return saved preferences (empty dict if absent)."""
        try:
            return json.loads(self._settings_path().read_text())
        except Exception:
            return {}

    def save_settings(self, data: dict[str, Any]) -> None:
        """Overwrite the settings file with *data*."""
        try:
            self._settings_path().write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def update_settings(self, **kwargs: Any) -> None:
        """Merge *kwargs* into saved settings (None values are ignored)."""
        data = self.load_settings()
        data.update({k: v for k, v in kwargs.items() if v is not None})
        self.save_settings(data)
