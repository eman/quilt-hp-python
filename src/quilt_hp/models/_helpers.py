from __future__ import annotations


def _id_variants(value: str | None) -> set[str]:
    """Return raw and normalized ID variants for matching resource IDs."""
    if not value:
        return set()
    raw = value.strip()
    if not raw:
        return set()
    tail_slash = raw.rsplit("/", 1)[-1]
    tail_colon = raw.rsplit(":", 1)[-1]
    variants = {raw, tail_slash, tail_colon, raw.casefold()}
    variants.add(tail_slash.casefold())
    variants.add(tail_colon.casefold())
    return {v for v in variants if v}


def lookup_hardware(hw_map: dict[str, object], hardware_id: str | None) -> object | None:
    """Resolve hardware objects across common ID formats."""
    for key in _id_variants(hardware_id):
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
