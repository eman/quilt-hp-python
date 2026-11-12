"""BLE direct-control client for a Quilt Dial (``BluetoothControlClient``).

Drives the Bluetooth control service the app added in 1.0.34: it reads live climate and damper
state from a Dial and writes setpoint/mode/fan/power commands straight over BLE, with no cloud.
This mirrors the app's installer "Remote Control" tool.

Requires the optional ``bleak`` dependency::

    pip install "quilt-hp-python[ble]"

Physical access is proven exactly as the app does it: the client reads the Dial's
``physical_access_challenge`` characteristic (its serial) on connect. There is no pairing,
bonding, or encryption — the protocol is raw protobuf on plain GATT characteristics.

RECONSTRUCTED FROM THE APP AND NOT YET VERIFIED AGAINST PHYSICAL HARDWARE. The GATT layout and
message shapes come from decompiling app 1.0.34; treat this as experimental.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from quilt_hp._proto import quilt_bluetooth_control_pb2 as ble
from quilt_hp.exceptions import QuiltBluetoothError
from quilt_hp.models.bluetooth import (
    BluetoothActionResult,
    ChangeCounters,
    ClimateControls,
    ClimateMode,
    ClimateOperation,
    ClimatePower,
    ClimateState,
    ClimateStatus,
    DamperState,
    FanSpeedMode,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

__all__ = [
    "BluetoothActionResult",
    "BluetoothControlClient",
    "ChangeCounters",
    "ClimateControls",
    "ClimateMode",
    "ClimateOperation",
    "ClimatePower",
    "ClimateState",
    "ClimateStatus",
    "DamperState",
    "FanSpeedMode",
    "discover_dials",
]

logger = logging.getLogger(__name__)

# GATT layout — see protocols/local/README.md "BLE Control Service".
CONTROL_SERVICE_UUID = "b3c0234b-6e46-4692-3b92-000000000000"
ACTION_REQUEST_UUID = "b3c0234b-6e46-4692-3b92-000000000001"  # write
ACTION_RESPONSE_UUID = "b3c0234b-6e46-4692-3b92-000000000002"  # notify
CLIMATE_CONTROLS_UUID = "b3c0234b-6e46-4692-3b92-000000000003"  # read
CLIMATE_STATE_UUID = "b3c0234b-6e46-4692-3b92-000000000004"  # read
CHANGE_COUNTERS_UUID = "b3c0234b-6e46-4692-3b92-000000000005"  # notify
DAMPER_STATE_UUID = "b3c0234b-6e46-4692-3b92-000000000006"  # read

# Physical-access challenge lives on the pairing service (read the serial to prove presence).
PHYSICAL_ACCESS_CHALLENGE_UUID = "f323923b-ee46-4296-b0c3-000000000006"

# The Dial advertises Quilt's manufacturer id while connectable for remote control.
QUILT_MANUFACTURER_ID = 0x0F60

DEFAULT_ACTION_TIMEOUT = 15.0


def _require_bleak() -> Any:
    try:
        import bleak
    except ImportError as exc:  # pragma: no cover - exercised via import guard test
        raise QuiltBluetoothError(
            "BLE control needs the 'bleak' package. Install it with: "
            'pip install "quilt-hp-python[ble]"'
        ) from exc
    return bleak


async def discover_dials(duration: float = 8.0) -> list[tuple[str, str | None]]:
    """Scan ``duration`` seconds for Quilt devices connectable for remote control.

    Matches devices advertising Quilt's manufacturer id. Returns ``(address, name)`` pairs.
    Requires ``bleak``.
    """
    bleak = _require_bleak()
    found: dict[str, str | None] = {}

    def _on_detect(device: Any, adv: Any) -> None:
        if QUILT_MANUFACTURER_ID in getattr(adv, "manufacturer_data", {}):
            found[device.address] = device.name

    scanner = bleak.BleakScanner(detection_callback=_on_detect)
    await scanner.start()
    try:
        await asyncio.sleep(duration)
    finally:
        await scanner.stop()
    return list(found.items())


class BluetoothControlClient:
    """Async client for a Dial's BLE control service.

    Use as an async context manager::

        async with BluetoothControlClient(address) as dial:
            state = await dial.read_climate_state()
            await dial.set_temperatures(heat_c=20.0)

    ``device`` is a BLE address string or any object ``bleak.BleakClient`` accepts.
    """

    def __init__(self, device: Any, *, action_timeout: float = DEFAULT_ACTION_TIMEOUT) -> None:
        self._device = device
        self._action_timeout = action_timeout
        self._bleak = _require_bleak()
        self._client: Any = self._bleak.BleakClient(device)
        self._serial: str | None = None
        self._action_responses: asyncio.Queue[bytes] = asyncio.Queue()

    @property
    def serial(self) -> str | None:
        """The Dial's serial, read from the physical-access challenge on connect."""
        return self._serial

    @property
    def is_connected(self) -> bool:
        return bool(getattr(self._client, "is_connected", False))

    async def __aenter__(self) -> BluetoothControlClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Connect, prove physical access, verify the control service, and subscribe."""
        await self._client.connect()
        try:
            challenge = await self._client.read_gatt_char(PHYSICAL_ACCESS_CHALLENGE_UUID)
            self._serial = bytes(challenge).decode("utf-8", "replace") or None
            if not self._has_control_service():
                raise QuiltBluetoothError("Device has no Bluetooth control service")
            await self._client.start_notify(ACTION_RESPONSE_UUID, self._on_action_response)
        except QuiltBluetoothError:
            await self.disconnect()
            raise
        except Exception as exc:
            await self.disconnect()
            raise QuiltBluetoothError(f"Failed to connect to Dial: {exc}") from exc

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:  # pragma: no cover - best-effort teardown
            logger.debug("Error disconnecting BLE client", exc_info=True)

    def _has_control_service(self) -> bool:
        services = getattr(self._client, "services", None)
        if services is None:
            return True  # some bleak versions/mocks don't expose a service list; trust connect
        uuids = {str(s.uuid).lower() for s in services}
        return CONTROL_SERVICE_UUID in uuids

    def _on_action_response(self, _char: Any, data: bytearray) -> None:
        self._action_responses.put_nowait(bytes(data))

    # -- reads ---------------------------------------------------------------

    async def read_climate_controls(self) -> ClimateControls:
        """The Dial's current control settings."""
        data = await self._client.read_gatt_char(CLIMATE_CONTROLS_UUID)
        msg = ble.BluetoothClimateControls()
        msg.ParseFromString(bytes(data))
        return ClimateControls.from_proto(msg)

    async def read_climate_state(self) -> ClimateState:
        """What the unit is doing right now."""
        data = await self._client.read_gatt_char(CLIMATE_STATE_UUID)
        msg = ble.BluetoothClimateState()
        msg.ParseFromString(bytes(data))
        return ClimateState.from_proto(msg)

    async def read_damper_state(self) -> DamperState:
        """Ducted-zone dampers seen on this device."""
        data = await self._client.read_gatt_char(DAMPER_STATE_UUID)
        msg = ble.BluetoothDamperState()
        msg.ParseFromString(bytes(data))
        return DamperState.from_proto(msg)

    async def subscribe_changes(self, callback: Callable[[ChangeCounters], None]) -> None:
        """Call ``callback`` whenever a change-counter bumps; re-read what moved."""

        def _on_change(_char: Any, data: bytearray) -> None:
            msg = ble.BluetoothChangeCounters()
            msg.ParseFromString(bytes(data))
            callback(ChangeCounters.from_proto(msg))

        await self._client.start_notify(CHANGE_COUNTERS_UUID, _on_change)

    # -- writes --------------------------------------------------------------

    async def set_power(self, on: bool, mode: ClimateMode | None = None) -> None:
        """Turn the unit on or off, optionally also setting the mode."""
        set_power = ble.BluetoothActionRequest.SetPower(
            power=ble.ClimatePower.ValueType(ClimatePower.ON if on else ClimatePower.OFF)
        )
        if mode is not None:
            set_power.mode = ble.ClimateMode.ValueType(mode)
        await self._submit(ble.BluetoothActionRequest(set_power=set_power))

    async def set_mode(self, mode: ClimateMode) -> None:
        """Set the climate mode (heat/cool/fan/auto)."""
        await self._submit(
            ble.BluetoothActionRequest(
                set_mode=ble.BluetoothActionRequest.SetMode(mode=ble.ClimateMode.ValueType(mode))
            )
        )

    async def set_temperatures(
        self, *, heat_c: float | None = None, cool_c: float | None = None
    ) -> None:
        """Set heat and/or cool setpoints in Celsius; omit either to leave it unchanged."""
        if heat_c is None and cool_c is None:
            raise ValueError("set_temperatures needs at least one of heat_c or cool_c")
        setpoints = ble.BluetoothActionRequest.SetTemperatureSetpoints()
        if heat_c is not None:
            setpoints.heat_setpoint_c = heat_c
        if cool_c is not None:
            setpoints.cool_setpoint_c = cool_c
        await self._submit(ble.BluetoothActionRequest(set_temperature_setpoints=setpoints))

    async def set_fan_speed(self, mode: FanSpeedMode, percent: int | None = None) -> None:
        """Set the fan to AUTO, or to PERCENT with a 0–100 level."""
        set_fan = ble.BluetoothActionRequest.SetFanSpeed(mode=ble.FanSpeedMode.ValueType(mode))
        if percent is not None:
            set_fan.fan_speed_percent = percent
        await self._submit(ble.BluetoothActionRequest(set_fan_speed=set_fan))

    async def _submit(self, request: ble.BluetoothActionRequest) -> None:
        """Write one action and wait for the device's response notification."""
        while not self._action_responses.empty():  # drop any stale response
            self._action_responses.get_nowait()
        await self._client.write_gatt_char(ACTION_REQUEST_UUID, request.SerializeToString())
        try:
            raw = await asyncio.wait_for(self._action_responses.get(), self._action_timeout)
        except TimeoutError as exc:
            raise QuiltBluetoothError("No action response from the Dial") from exc
        response = ble.BluetoothActionResponse()
        response.ParseFromString(raw)
        result = BluetoothActionResult(response.result)
        if result != BluetoothActionResult.OK:
            detail = f": {response.message}" if response.message else ""
            raise QuiltBluetoothError(
                f"Dial rejected the action ({result}){detail}", result=result
            )
