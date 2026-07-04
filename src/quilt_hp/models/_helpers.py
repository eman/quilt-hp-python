from __future__ import annotations

from datetime import UTC, datetime


def local_comms_last_session_change(local_comms_status: object) -> datetime | None:
    """Return ``LocalCommsStatus.last_session_change_ts`` as an aware datetime.

    Returns ``None`` when the status message or timestamp is absent.
    """
    ts = getattr(local_comms_status, "last_session_change_ts", None)
    seconds = getattr(ts, "seconds", 0) if ts is not None else 0
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def _id_variant_keys(raw: str) -> tuple[str, ...]:
    """Return ID variant keys in deterministic priority order (exact → tail → casefold)."""
    tail_slash = raw.rsplit("/", 1)[-1]
    tail_colon = raw.rsplit(":", 1)[-1]
    return (
        raw,
        tail_slash,
        tail_colon,
        raw.casefold(),
        tail_slash.casefold(),
        tail_colon.casefold(),
    )


def _id_variants(value: str | None) -> set[str]:
    """Return raw and normalized ID variants for matching resource IDs."""
    if not value:
        return set()
    raw = value.strip()
    if not raw:
        return set()
    return {v for v in _id_variant_keys(raw) if v}


def lookup_hardware(hw_map: dict[str, object], hardware_id: str | None) -> object | None:
    """Resolve hardware objects across common ID formats.

    Keys are tried in deterministic priority order: exact → tail (after last
    ``/`` or ``:`` separator) → casefold variants, matching the behaviour of
    the original implementation.
    """
    if not hardware_id:
        return None
    raw = hardware_id.strip()
    if not raw:
        return None
    for key in _id_variant_keys(raw):
        hw = hw_map.get(key)
        if hw is not None:
            return hw
    return None


def parse_wifi_state(
    proto: object,
) -> tuple[str | None, str | None, int | None, str | None, int | None]:
    """Extract WiFi fields while preserving explicit zero signal values.

    Returns ``(ssid, ip, signal_dbm, bssid, frequency_mhz)``. ``bssid`` and
    ``frequency_mhz`` are wire-present on the shared ``WifiState`` message
    used by both QSM and Controller hosted-wifi state (confirmed via raw
    proto capture 2026-07-03) and identify which physical AP radio/band a
    device is associated with.
    """
    ssid = getattr(proto, "ssid", "") or None
    ip = getattr(proto, "ipv4_address", None) or None
    signal = getattr(proto, "signal_level_dbm", None)
    bssid = getattr(proto, "bssid", "") or None
    frequency_mhz = getattr(proto, "frequency_mhz", None) or None
    return ssid, ip, (signal if signal is not None else None), bssid, frequency_mhz
