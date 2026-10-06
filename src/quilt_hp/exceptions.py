"""Exception hierarchy for quilt_hp."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quilt_hp.models.actions import ActionOutcome


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

    def __init__(self, outcome: ActionOutcome) -> None:
        super().__init__(f"Action failed: {outcome.failure_reason or 'no reason given'}")
        self.outcome: ActionOutcome = outcome
