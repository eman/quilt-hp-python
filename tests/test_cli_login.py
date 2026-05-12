"""Tests for CLI login OTP prompting behavior."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import ClassVar
from unittest.mock import patch

from quilt_hp.cli import main as cli_main
from quilt_hp.exceptions import QuiltAuthError


class _FakeClient:
    """Test double for QuiltClient used by CLI login tests."""

    events: ClassVar[list[str]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def login(self, otp_callback: Callable[[str], object] | None = None) -> None:
        if otp_callback is None:
            _FakeClient.events.append("silent-login")
            raise QuiltAuthError("need OTP")

        _FakeClient.events.append("otp-login-start")
        otp = otp_callback("user@example.com")
        if inspect.isawaitable(otp):
            otp = await otp
        _FakeClient.events.append(f"otp={otp}")


def test_login_prompts_after_otp_flow_starts() -> None:
    _FakeClient.events.clear()

    def _fake_prompt(_label: str) -> str:
        _FakeClient.events.append("prompt")
        return "123456"

    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _FakeClient),
        patch.object(cli_main.typer, "prompt", side_effect=_fake_prompt),
    ):
        cli_main.login(email="user@example.com", home=None)

    assert _FakeClient.events == [
        "silent-login",
        "otp-login-start",
        "prompt",
        "otp=123456",
    ]
