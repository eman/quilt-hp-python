from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

from typer.testing import CliRunner

from quilt_hp.cli import main as cli_main
from quilt_hp.models.enums import HVACMode

runner = CliRunner()


def test_version_option_outputs_package_version() -> None:
    result = runner.invoke(cli_main.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.2.2"


class _FakeClient:
    set_calls: ClassVar[list[tuple[str, HVACMode | None, float | None, float | None]]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def login(self) -> None:
        return None

    async def list_comfort_settings(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                name="Sleep",
                type=SimpleNamespace(name="USER"),
                hvac_mode=HVACMode.HEAT,
                heating_setpoint_c=19.0,
                cooling_setpoint_c=25.0,
                fan_speed=SimpleNamespace(name="AUTO"),
            )
        ]

    async def get_snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(
            timezone="UTC",
            spaces=[SimpleNamespace(id="space-1", name="Living")],
            rooms=[SimpleNamespace(id="space-1", name="Living")],
            comfort_settings=[SimpleNamespace(id="c1", name="Sleep")],
            schedule_days=[
                SimpleNamespace(
                    id="d1",
                    name="Weekday",
                    events=[SimpleNamespace(start_time="07:00", comfort_setting_id="c1")],
                )
            ],
            schedule_weeks=[
                SimpleNamespace(
                    space_id="space-1",
                    days=[
                        SimpleNamespace(day_id="d1", weekday_name="Mon"),
                        SimpleNamespace(day_id="d1", weekday_name="Tue"),
                    ],
                )
            ],
        )

    async def get_energy(self, *_args: object, **_kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(space_id="space-1", total_kwh=2.5)]

    async def set_space(
        self,
        space_id: str,
        *,
        mode: HVACMode | None,
        heat_setpoint_c: float | None,
        cool_setpoint_c: float | None,
    ) -> None:
        self.set_calls.append((space_id, mode, heat_setpoint_c, cool_setpoint_c))


def test_presets_schedules_energy_and_set_commands() -> None:
    _FakeClient.set_calls.clear()
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", "Home")),
        patch.object(cli_main, "QuiltClient", _FakeClient),
    ):
        presets = runner.invoke(cli_main.app, ["presets"])
        schedules = runner.invoke(cli_main.app, ["schedules"])
        energy_week = runner.invoke(cli_main.app, ["energy", "--period", "week"])
        energy_month = runner.invoke(cli_main.app, ["energy", "--period", "month"])
        set_ok = runner.invoke(
            cli_main.app,
            ["set", "Living", "--mode", "COOL", "--heat", "19", "--cool", "24"],
        )

    assert presets.exit_code == 0
    assert "Comfort Settings" in presets.stdout
    assert schedules.exit_code == 0
    assert "Weekday" in schedules.stdout
    assert energy_week.exit_code == 0
    assert "WEEK" in energy_week.stdout
    assert energy_month.exit_code == 0
    assert "MONTH" in energy_month.stdout
    assert set_ok.exit_code == 0
    assert _FakeClient.set_calls
    space_id, mode, heat, cool = _FakeClient.set_calls[0]
    assert space_id == "space-1"
    assert mode == HVACMode.COOL
    assert heat == 19.0
    assert cool == 24.0


def test_set_command_errors_for_unknown_room() -> None:
    class _NoRoomClient(_FakeClient):
        async def get_snapshot(self) -> SimpleNamespace:
            return SimpleNamespace(rooms=[])

    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _NoRoomClient),
    ):
        result = runner.invoke(cli_main.app, ["set", "Missing Room"])

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_tui_command_handles_missing_optional_dependency(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    original_import = __import__

    def _fake_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name == "quilt_hp.cli.tui":
            raise ImportError("no textual")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    with patch.object(cli_main, "_resolve", return_value=("user@example.com", None)):
        result = runner.invoke(cli_main.app, ["tui"])
    assert result.exit_code == 1


def test_tui_command_runs_when_module_available(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _FakeApp:
        ran = False

        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(self) -> None:
            _FakeApp.ran = True

    fake_module = ModuleType("quilt_hp.cli.tui")
    fake_module.QuiltApp = _FakeApp  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "quilt_hp.cli.tui", fake_module)

    with patch.object(cli_main, "_resolve", return_value=("user@example.com", None)):
        result = runner.invoke(cli_main.app, ["tui"])

    assert result.exit_code == 0
    assert _FakeApp.ran is True


def test_resolve_without_email_exits(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        cli_main, "_settings", SimpleNamespace(load=lambda: SimpleNamespace(email=None, home=None))
    )
    monkeypatch.setattr(cli_main, "_store", SimpleNamespace(list_emails=lambda: []))

    with patch.object(cli_main.console, "print"):
        try:
            cli_main._resolve(None, None)
            raise AssertionError("expected typer.Exit")
        except cli_main.typer.Exit as exc:
            assert exc.exit_code == 1


def test_energy_day_branch_uses_space_fallback_name() -> None:
    class _EnergyClient(_FakeClient):
        async def get_energy(self, *_args: object, **_kwargs: object) -> list[SimpleNamespace]:
            return [SimpleNamespace(space_id="missing-space", total_kwh=1.0)]

        async def get_snapshot(self) -> SimpleNamespace:
            return SimpleNamespace(timezone="UTC", spaces=[])

    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _EnergyClient),
    ):
        result = runner.invoke(cli_main.app, ["energy", "--period", "day"])

    assert result.exit_code == 0
    assert "DAY" in result.stdout
