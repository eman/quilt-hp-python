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


class QuiltPreconditionError(QuiltError):
    """The server refused because the system isn't set up for the request yet.

    For example, listing certified installer partners needs the system's address.
    The message is the server's explanation.
    """


class QuiltStreamError(QuiltError):
    """Error in the NotifierService bidirectional stream."""


class QuiltActionError(QuiltError):
    """The server reported that an action failed (``ActionResult.FAILED``).

    ``outcome`` holds the server's answer, including ``failure_reason``.
    """

    def __init__(self, outcome: object) -> None:
        reason = getattr(outcome, "failure_reason", None) or "no reason given"
        super().__init__(f"Action failed: {reason}")
        self.outcome = outcome
