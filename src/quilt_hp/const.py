"""Constants for the Quilt cloud API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Environment(Enum):
    """Quilt API environment."""

    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


@dataclass(frozen=True, slots=True)
class _EndpointConfig:
    grpc_host: str
    token_host: str


_ENDPOINTS: dict[Environment, _EndpointConfig] = {
    Environment.PROD: _EndpointConfig(
        grpc_host="api.prod.quilt.cloud:443",
        token_host="token.prod.quilt.cloud",
    ),
    Environment.STAGING: _EndpointConfig(
        grpc_host="api.staging.quilt.cloud:443",
        token_host="token.staging.quilt.cloud",
    ),
    Environment.DEV: _EndpointConfig(
        grpc_host="api.dev.quilt.cloud:443",
        token_host="token.dev.quilt.cloud",
    ),
}


def grpc_host(env: Environment) -> str:
    """Return the gRPC host:port for the given environment."""
    return _ENDPOINTS[env].grpc_host


# AWS Cognito configuration (confirmed from live capture)
COGNITO_REGION = "us-west-2"
COGNITO_CLIENT_ID = "6lef74vtc8p7pgu47nmqubd9vn"

# App version sent with every gRPC call
APP_VERSION = "1.0.25"

# Common placeholder / sentinel values seen in app and wire data.
EMPTY_COMFORT_SETTING_ID_SENTINEL: str = ""
UNSPECIFIED_HEAT_SETPOINT_SENTINEL_C: float = 0.0
UNSPECIFIED_COOL_SETPOINT_SENTINEL_C: float = 0.0
LOUVER_FIXED_POSITION_SENTINEL: float = 0.0
UNSET_MAX_FAN_SPEED_RPM_SENTINEL: float = 0.0
ABSENT_FAN_SPEED_MODE_SENTINEL: int = 0
PROTO_TIMESTAMP_UNSET_SECONDS: int = 0
UNKNOWN_SCHEDULE_SORT_ORDER_SENTINEL: int = 2_147_483_647

# Sentinel setpoint values used by the STANDBY comfort setting type.
# When a space is in STANDBY, heat/cool setpoints are meaningless (the unit
# is off).  The app fills them with these extreme out-of-range values rather
# than omitting the fields.  Any UI should treat these as "no real setpoint"
# and suppress display of the numeric values.
# Source: ComfortSettings.kt — ComfortSettingType.STANDBY default attributes.
STANDBY_HEAT_SENTINEL_C: float = 8.0
STANDBY_COOL_SENTINEL_C: float = 40.0

# gRPC keepalive settings
GRPC_CHANNEL_OPTIONS: list[tuple[str, int]] = [
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.http2.max_pings_without_data", 0),
]
