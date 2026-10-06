"""Results and colours for the action API (``QuiltClient.apply_*``)."""

from __future__ import annotations

from dataclasses import dataclass

from quilt_hp.models.enums import ActionResult


@dataclass(slots=True, frozen=True)
class ActionOutcome:
    """The server's answer to a submitted action."""

    result: ActionResult
    action_id: str | None = None
    failure_reason: str | None = None

    @property
    def ok(self) -> bool:
        """True when every target applied the action."""
        return self.result == ActionResult.SUCCESS


@dataclass(slots=True, frozen=True)
class RgbwColor:
    """A custom LED colour; each channel 0–255."""

    red: int = 0
    green: int = 0
    blue: int = 0
    white: int = 0

    def __post_init__(self) -> None:
        for name in ("red", "green", "blue", "white"):
            value = getattr(self, name)
            if not 0 <= value <= 255:
                raise ValueError(f"{name} must be 0–255, got {value}")
