"""quilt_hp — Async Python client for Quilt mini-split HVAC systems."""

from quilt_hp.auth import OtpCallback
from quilt_hp.client import QuiltClient
from quilt_hp.const import Environment
from quilt_hp.exceptions import (
    QuiltAuthError,
    QuiltConnectionError,
    QuiltError,
    QuiltNotFoundError,
    QuiltStreamError,
)
from quilt_hp.services.streaming import NotifierStream, StreamEvent
from quilt_hp.tokens import (
    CachedTokens,
    LegacyTokenStore,
    RefreshFailureAction,
    TokenRefreshContext,
    TokenRefreshHooks,
    TokenRefreshPolicy,
    TokenRefreshReason,
    TokenStore,
)

__version__ = "0.5.6"

__all__ = [
    "CachedTokens",
    "Environment",
    "LegacyTokenStore",
    "NotifierStream",
    "OtpCallback",
    "QuiltAuthError",
    "QuiltClient",
    "QuiltConnectionError",
    "QuiltError",
    "QuiltNotFoundError",
    "QuiltStreamError",
    "RefreshFailureAction",
    "StreamEvent",
    "TokenRefreshContext",
    "TokenRefreshHooks",
    "TokenRefreshPolicy",
    "TokenRefreshReason",
    "TokenStore",
]
