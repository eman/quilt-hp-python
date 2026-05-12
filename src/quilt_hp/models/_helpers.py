from __future__ import annotations


def lookup_hardware(hw_map: dict[str, object], hardware_id: str | None) -> object | None:
    """Resolve hardware objects across common ID formats."""
    if not hardware_id:
        return None
    raw = hardware_id.strip()
    if not raw:
        return None
    keys = (
        raw,
        raw.rsplit("/", 1)[-1],
        raw.rsplit(":", 1)[-1],
        raw.casefold(),
        raw.rsplit("/", 1)[-1].casefold(),
        raw.rsplit(":", 1)[-1].casefold(),
    )
    for key in keys:
        hw = hw_map.get(key)
        if hw is not None:
            return hw
    return None


def parse_wifi_state(proto: object) -> tuple[str | None, str | None, int | None]:
    """Extract WiFi fields while preserving explicit zero signal values."""
    ssid = getattr(proto, "ssid", "") or None
    ip = getattr(proto, "ipv4_address", None) or None
    signal = getattr(proto, "signal_level_dbm", None)
    return ssid, ip, signal if signal is not None else None
