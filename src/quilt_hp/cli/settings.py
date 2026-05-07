"""Settings persistence for non-secret CLI/TUI preferences."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quilt_hp._paths import app_config_dir

_SETTINGS_SCHEMA_VERSION = 1


@dataclass(slots=True)
class Settings:
    """Non-secret user preferences shared by CLI and TUI."""

    email: str | None = None
    home: str | None = None
    use_fahrenheit: bool = False
    dark: bool | None = None


class SettingsStore:
    """Platform-aware settings storage with migration and recovery."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    def _settings_path(self) -> Path:
        if self._path is not None:
            return self._path
        return app_config_dir() / "settings.json"

    def load(self) -> Settings:
        """Load settings, migrating legacy files and recovering corruption."""
        path = self._settings_path()
        try:
            payload = json.loads(path.read_text())
        except FileNotFoundError:
            return Settings()
        except Exception:
            return self._recover_corruption("invalid-json")

        if not isinstance(payload, dict):
            return self._recover_corruption("invalid-shape")

        schema_version = payload.get("schema_version")
        if schema_version is None:
            settings = self._from_legacy(payload)
            self.save(settings)
            return settings

        if schema_version != _SETTINGS_SCHEMA_VERSION:
            return self._recover_corruption("unsupported-schema")

        prefs = payload.get("preferences")
        if not isinstance(prefs, dict):
            return self._recover_corruption("invalid-preferences")
        return self._coerce(prefs)

    def save(self, settings: Settings) -> None:
        """Persist settings using versioned schema and atomic replace."""
        payload = {
            "schema_version": _SETTINGS_SCHEMA_VERSION,
            "preferences": asdict(settings),
        }
        self._atomic_write(payload)

    def update(
        self,
        *,
        email: str | None = None,
        home: str | None = None,
        use_fahrenheit: bool | None = None,
        dark: bool | None = None,
    ) -> Settings:
        """Update selected settings fields and persist."""
        settings = self.load()
        if email is not None:
            settings.email = email
        if home is not None:
            settings.home = home
        if use_fahrenheit is not None:
            settings.use_fahrenheit = use_fahrenheit
        if dark is not None:
            settings.dark = dark
        self.save(settings)
        return settings

    def _from_legacy(self, payload: dict[str, object]) -> Settings:
        return self._coerce(payload)

    def _coerce(self, payload: dict[str, object]) -> Settings:
        email = payload.get("email")
        home = payload.get("home")
        dark = payload.get("dark")
        return Settings(
            email=email if isinstance(email, str) else None,
            home=home if isinstance(home, str) else None,
            use_fahrenheit=bool(payload.get("use_fahrenheit", False)),
            dark=dark if isinstance(dark, bool) else None,
        )

    def _atomic_write(self, payload: dict[str, object]) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, path)

    def _recover_corruption(self, reason: str) -> Settings:
        path = self._settings_path()
        settings = Settings()
        if path.exists():
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = path.with_name(f"{path.name}.corrupt-{timestamp}-{reason}")
            path.replace(backup)
        self.save(settings)
        return settings
