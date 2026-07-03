from __future__ import annotations

from datetime import UTC, datetime

from quilt_hp.const import PROTO_TIMESTAMP_UNSET_SECONDS


def proto_has_field(proto: object, name: str) -> bool:
    """Return True when a message-typed field is present on the wire.

    Works with generated protobuf messages (via ``HasField``) and with
    lightweight test stubs (attribute exists and is not ``None``).  proto3
    scalar fields without presence semantics (``HasField`` raises
    ``ValueError``) fall back to the attribute check.

    This is the only reliable proto3 absence test: truthiness does not work
    because an unset sub-message returns a truthy default instance, and
    ``getattr(msg, field, None)`` never returns ``None`` for real protos.
    """
    has_field = getattr(proto, "HasField", None)
    if callable(has_field):
        try:
            return bool(has_field(name))
        except ValueError:
            pass  # field without explicit presence — fall back to attribute check
    return getattr(proto, name, None) is not None


def present_submsg(proto: object, name: str) -> object | None:
    """Return the sub-message when present on the wire, else ``None``."""
    return getattr(proto, name) if proto_has_field(proto, name) else None


def timestamp_or_none(ts: object) -> datetime | None:
    """Convert a proto Timestamp to a datetime, or None when unset/absent."""
    if ts is None:
        return None
    seconds = getattr(ts, "seconds", PROTO_TIMESTAMP_UNSET_SECONDS)
    if seconds == PROTO_TIMESTAMP_UNSET_SECONDS:
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


def parse_wifi_state(proto: object) -> tuple[str | None, str | None, int | None]:
    """Extract WiFi fields while preserving explicit zero signal values."""
    ssid = getattr(proto, "ssid", "") or None
    ip = getattr(proto, "ipv4_address", None) or None
    signal = getattr(proto, "signal_level_dbm", None)
    return ssid, ip, signal if signal is not None else None
