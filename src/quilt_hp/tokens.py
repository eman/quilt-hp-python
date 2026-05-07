"""Token types and storage protocol for Quilt authentication.

The core library defines the data types and the ``TokenStore`` protocol.
Persistence is the caller's responsibility — the CLI provides ``FileStore``
in ``quilt_hp.cli.store``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

_TOKEN_BUFFER_S = 300  # treat tokens as expired 5 min before actual expiry


@dataclass(slots=True)
class CachedTokens:
    """A Cognito IdToken plus its refresh token and expiry timestamp."""

    id_token: str
    refresh_token: str
    expires_at: float  # unix timestamp

    @property
    def is_expired(self) -> bool:
        """True if the IdToken has expired (with a 5-minute safety buffer)."""
        return time.time() > self.expires_at - _TOKEN_BUFFER_S


class TokenStore(Protocol):
    """Protocol for token persistence.

    Implement this to integrate with any storage backend
    (filesystem, HA secure storage, database, keychain, …).
    """

    def load(self, email: str) -> CachedTokens | None:
        """Return cached tokens for *email*, or None if absent / invalid."""
        ...

    def save(self, email: str, tokens: CachedTokens) -> None:
        """Persist *tokens* for *email*."""
        ...
