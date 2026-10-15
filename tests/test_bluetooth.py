"""Tests for the BLE direct-control client (quilt_hp.bluetooth).

No real Bluetooth: a fake ``bleak`` module and a fake GATT client drive the real code path,
so the proto encode/decode, handshake, and action round-trip are exercised end to end.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import types
from typing import Any

import pytest

from quilt_hp._proto import quilt_bluetooth_control_pb2 as ble
from quilt_hp.bluetooth import (
    ACTION_RESPONSE_UUID,
    CHANGE_COUNTERS_UUID,
    CLIMATE_CONTROLS_UUID,
    CLIMATE_STATE_UUID,
    CONTROL_SERVICE_UUID,
    DAMPER_STATE_UUID,
    BluetoothControlClient,
    discover_dials,
)
from quilt_hp.exceptions import QuiltBluetoothError
from quilt_hp.models.bluetooth import (
    BluetoothActionResult,
    ChangeCounters,
    ClimateMode,
    ClimateOperation,
    ClimatePower,
    ClimateStatus,
    FanSpeedMode,
    PresenceResult,
)


class _FakeService:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid


class _FakeBleakClient:
    """Minimal stand-in for bleak.BleakClient with scripted characteristic values."""

    def __init__(self, device: Any, *, has_control: bool = True) -> None:
        self.device = device
        self.is_connected = False
        self._notify: dict[str, Any] = {}
        self.written: list[tuple[str, bytes]] = []
        self.reads: dict[str, bytes] = {}
        self.services = [_FakeService("f323923b-ee46-4296-b0c3-000000000000")]
        if has_control:
            self.services.append(_FakeService(CONTROL_SERVICE_UUID))
        # physical-access challenge returns the serial
        self.reads["f323923b-ee46-4296-b0c3-000000000006"] = b"QS1-TESTDIAL"

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def read_gatt_char(self, uuid: str) -> bytes:
        return self.reads[uuid]

    async def write_gatt_char(self, uuid: str, data: bytes) -> None:
        self.written.append((uuid, bytes(data)))
        # Echo back an OK action response on the notify channel, as a real device would.
        cb = self._notify.get(ACTION_RESPONSE_UUID)
        if cb is not None:
            resp = ble.BluetoothActionResponse(result=ble.RESULT_OK)
            cb(None, bytearray(resp.SerializeToString()))

    async def start_notify(self, uuid: str, callback: Any) -> None:
        self._notify[uuid] = callback


@pytest.fixture
def fake_bleak(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Install a fake ``bleak`` module so BluetoothControlClient imports it."""
    mod = types.ModuleType("bleak")
    mod.BleakClient = _FakeBleakClient  # type: ignore[attr-defined]
    mod.BleakScanner = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bleak", mod)
    return mod


async def test_connect_reads_serial_and_requires_control_service(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        assert dial.serial == "QS1-TESTDIAL"
        assert dial.is_connected


async def test_connect_without_control_service_raises(
    fake_bleak: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fake_bleak, "BleakClient", lambda d: _FakeBleakClient(d, has_control=False)
    )
    with pytest.raises(QuiltBluetoothError, match="no Bluetooth control service"):
        async with BluetoothControlClient("AA:BB"):
            pass


async def test_read_climate_state(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        state = ble.BluetoothClimateState(
            status=ble.CLIMATE_STATUS_RUNNING,
            operation=ble.CLIMATE_OPERATION_HEAT,
            ambient_temperature_c=21.5,
        )
        dial._client.reads[CLIMATE_STATE_UUID] = state.SerializeToString()
        result = await dial.read_climate_state()
        assert result.status is ClimateStatus.RUNNING
        assert result.operation is ClimateOperation.HEAT
        assert result.ambient_temperature_c == pytest.approx(21.5)


async def test_set_temperatures_encodes_and_awaits_ok(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        await dial.set_temperatures(heat_c=20.0)
        uuid, payload = dial._client.written[-1]
        req = ble.BluetoothActionRequest()
        req.ParseFromString(payload)
        assert req.WhichOneof("action") == "set_temperature_setpoints"
        assert req.set_temperature_setpoints.heat_setpoint_c == pytest.approx(20.0)
        assert not req.set_temperature_setpoints.HasField("cool_setpoint_c")


async def test_set_power_with_mode(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        await dial.set_power(True, mode=ClimateMode.HEAT)
        req = ble.BluetoothActionRequest()
        req.ParseFromString(dial._client.written[-1][1])
        assert req.set_power.power == ClimatePower.ON
        assert req.set_power.mode == ClimateMode.HEAT


async def test_set_fan_speed_percent(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        await dial.set_fan_speed(FanSpeedMode.PERCENT, percent=60)
        req = ble.BluetoothActionRequest()
        req.ParseFromString(dial._client.written[-1][1])
        assert req.set_fan_speed.mode == FanSpeedMode.PERCENT
        assert req.set_fan_speed.fan_speed_percent == 60


async def test_set_temperatures_needs_an_argument(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        with pytest.raises(ValueError, match="at least one"):
            await dial.set_temperatures()


async def test_rejected_action_raises_with_result(
    fake_bleak: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Rejecting(_FakeBleakClient):
        async def write_gatt_char(self, uuid: str, data: bytes) -> None:
            self.written.append((uuid, bytes(data)))
            cb = self._notify[ACTION_RESPONSE_UUID]
            resp = ble.BluetoothActionResponse(result=ble.RESULT_UNAVAILABLE, message="busy")
            cb(None, bytearray(resp.SerializeToString()))

    monkeypatch.setattr(fake_bleak, "BleakClient", _Rejecting)
    async with BluetoothControlClient("AA:BB") as dial:
        with pytest.raises(QuiltBluetoothError, match="busy") as excinfo:
            await dial.set_mode(ClimateMode.COOL)
        assert excinfo.value.result is BluetoothActionResult.UNAVAILABLE


async def test_action_timeout(fake_bleak: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Silent(_FakeBleakClient):
        async def write_gatt_char(self, uuid: str, data: bytes) -> None:
            self.written.append((uuid, bytes(data)))  # never sends a response

    monkeypatch.setattr(fake_bleak, "BleakClient", _Silent)
    async with BluetoothControlClient("AA:BB", action_timeout=0.05) as dial:
        with pytest.raises(QuiltBluetoothError, match="No action response"):
            await dial.set_mode(ClimateMode.COOL)


async def test_read_climate_controls(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        controls = ble.BluetoothClimateControls(
            power=ble.CLIMATE_POWER_ON,
            mode=ble.CLIMATE_MODE_COOL,
            fan_speed_mode=ble.FAN_SPEED_MODE_PERCENT,
            cool_setpoint_c=23.0,
            fan_speed_percent=40,
        )
        dial._client.reads[CLIMATE_CONTROLS_UUID] = controls.SerializeToString()
        result = await dial.read_climate_controls()
        assert result.power is ClimatePower.ON
        assert result.mode is ClimateMode.COOL
        assert result.fan_speed_mode is FanSpeedMode.PERCENT
        assert result.cool_setpoint_c == pytest.approx(23.0)
        assert result.heat_setpoint_c is None
        assert result.fan_speed_percent == 40


async def test_read_damper_state(fake_bleak: Any) -> None:
    async with BluetoothControlClient("AA:BB") as dial:
        dampers = ble.BluetoothDamperState(
            dampers=[
                ble.BluetoothDamperState.Damper(
                    channel_index=0, presence=ble.PRESENCE_RESULT_PRESENT
                ),
                ble.BluetoothDamperState.Damper(
                    channel_index=1, presence=ble.PRESENCE_RESULT_ABSENT
                ),
            ]
        )
        dial._client.reads[DAMPER_STATE_UUID] = dampers.SerializeToString()
        result = await dial.read_damper_state()
        assert [(d.channel_index, d.presence) for d in result.dampers] == [
            (0, PresenceResult.PRESENT),
            (1, PresenceResult.ABSENT),
        ]


async def test_subscribe_changes_delivers_counters(fake_bleak: Any) -> None:
    received: list[ChangeCounters] = []
    async with BluetoothControlClient("AA:BB") as dial:
        await dial.subscribe_changes(received.append)
        callback = dial._client._notify[CHANGE_COUNTERS_UUID]
        counters = ble.BluetoothChangeCounters(climate_controls=3, climate_state=5, damper_state=1)
        callback(None, bytearray(counters.SerializeToString()))
    assert received == [ChangeCounters(climate_controls=3, climate_state=5, damper_state=1)]


async def test_discover_dials(monkeypatch: pytest.MonkeyPatch, fake_bleak: Any) -> None:
    class _Device:
        def __init__(self, address: str, name: str) -> None:
            self.address, self.name = address, name

    class _FakeScanner:
        def __init__(self, detection_callback: Any) -> None:
            self._cb = detection_callback

        async def start(self) -> None:
            self._cb(_Device("AA:BB", "Quilt Dial"), types.SimpleNamespace(manufacturer_data={0x0F60: b""}))
            self._cb(_Device("CC:DD", "Other"), types.SimpleNamespace(manufacturer_data={0x1234: b""}))

        async def stop(self) -> None:
            pass

    monkeypatch.setattr(fake_bleak, "BleakScanner", _FakeScanner)
    found = await discover_dials(duration=0.0)
    assert found == [("AA:BB", "Quilt Dial")]


def test_missing_bleak_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _no_bleak(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "bleak":
            raise ImportError("no bleak")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "bleak", raising=False)
    monkeypatch.setattr(builtins, "__import__", _no_bleak)
    with pytest.raises(QuiltBluetoothError, match="bleak"):
        BluetoothControlClient("AA:BB")


def test_library_usable_without_bleak_installed() -> None:
    """Importing and using the non-BLE library must not require ``bleak``.

    Runs in a subprocess with ``bleak`` blocked at the import system, so the guarantee holds
    regardless of whether ``bleak`` happens to be installed in the test environment.
    """
    script = textwrap.dedent(
        """
        import sys, builtins, asyncio
        _real = builtins.__import__
        def _block(name, *a, **k):
            if name == "bleak" or name.startswith("bleak."):
                raise ImportError("bleak blocked for test")
            return _real(name, *a, **k)
        builtins.__import__ = _block

        import quilt_hp
        from quilt_hp import QuiltClient, BluetoothControlClient, discover_dials, QuiltBluetoothError

        # Core library imports and constructs with no bleak anywhere.
        assert "bleak" not in sys.modules, "importing quilt_hp pulled in bleak"
        QuiltClient("user@example.com")

        # BLE entry points fail with a clear, actionable error rather than ImportError.
        try:
            BluetoothControlClient("AA:BB")
        except QuiltBluetoothError as exc:
            assert "bleak" in str(exc)
        else:
            raise AssertionError("expected QuiltBluetoothError without bleak")

        try:
            asyncio.run(discover_dials(0.0))
        except QuiltBluetoothError as exc:
            assert "bleak" in str(exc)
        else:
            raise AssertionError("expected QuiltBluetoothError without bleak")

        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok", result.stdout
