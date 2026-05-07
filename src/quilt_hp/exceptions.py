"""Exception hierarchy for quilt_hp."""

from __future__ import annotations


class QuiltError(Exception):
    """Base exception for all quilt_hp errors."""


class QuiltAuthError(QuiltError):
    """Authentication failed (OTP rejected, refresh expired, Cognito error)."""


class QuiltConnectionError(QuiltError):
    """Could not connect to the Quilt gRPC API."""


class QuiltNotFoundError(QuiltError):
    """Requested resource (system, space, IDU) was not found."""


class QuiltStreamError(QuiltError):
    """Error in the NotifierService bidirectional stream."""
