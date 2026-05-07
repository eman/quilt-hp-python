"""Platform-appropriate config directory for quilt-hp.

  macOS  → ~/Library/Application Support/quilt-hp/
  Linux  → $XDG_CONFIG_HOME/quilt-hp/  (default ~/.config/quilt-hp/)
  Windows → %APPDATA%\\quilt-hp\\

Files
-----
  tokens.json    Cached Cognito tokens, keyed by email
  settings.json  CLI/TUI user preferences (email, home, use_fahrenheit, dark)
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir

_APP = "quilt-hp"


def app_config_dir() -> Path:
    """Return the platform-appropriate config directory, creating if needed."""
    d = Path(user_config_dir(_APP))
    d.mkdir(parents=True, exist_ok=True)
    return d
