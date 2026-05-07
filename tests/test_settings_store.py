"""Tests for versioned settings persistence and recovery."""

from __future__ import annotations

import json
from pathlib import Path

from quilt_hp.cli.settings import SettingsStore


def test_migrates_legacy_settings_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "email": "user@test.com",
                "home": "My Home",
                "use_fahrenheit": True,
                "dark": False,
            }
        )
    )
    store = SettingsStore(path)

    settings = store.load()
    migrated_payload = json.loads(path.read_text())

    assert settings.email == "user@test.com"
    assert settings.home == "My Home"
    assert settings.use_fahrenheit is True
    assert settings.dark is False
    assert migrated_payload == {
        "schema_version": 1,
        "preferences": {
            "email": "user@test.com",
            "home": "My Home",
            "use_fahrenheit": True,
            "dark": False,
        },
    }


def test_recovers_from_corrupt_settings_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not-valid-json")
    store = SettingsStore(path)

    settings = store.load()

    assert settings.email is None
    assert settings.home is None
    assert settings.use_fahrenheit is False
    assert settings.dark is None
    assert json.loads(path.read_text()) == {
        "schema_version": 1,
        "preferences": {
            "email": None,
            "home": None,
            "use_fahrenheit": False,
            "dark": None,
        },
    }
    backups = list(tmp_path.glob("settings.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{not-valid-json"
