# Build a Home Assistant custom component

This guide shows how to build a Home Assistant custom component that exposes Quilt rooms as `climate` entities with real-time updates through the streaming API.

---

## Architecture overview

A Quilt HA component uses two parts:

1. **`DataUpdateCoordinator`**: Manages the `QuiltClient` connection, holds the `SystemSnapshot`, and drives entity updates.
2. **Entity classes**: Translate `Space` and `IndoorUnit` models into Home Assistant platform abstractions.

The coordinator uses an initial snapshot fetch on `async_setup_entry`, then a `NotifierStream` for real-time diffs. Polling is configured as a long-TTL fallback only.

```
HA event loop
└── QuiltCoordinator (DataUpdateCoordinator)
    ├── QuiltClient (gRPC channel + token store)
    ├── SystemSnapshot  ← full state in-memory
    └── NotifierStream  ← real-time diffs → async_set_updated_data()
        └── on_space_update, on_indoor_unit_update,
            on_controller_update, on_qsm_update
```

---

## Step 1: Implement the token store

To use HA's persistent JSON storage for tokens:

```python
from __future__ import annotations
import logging
from homeassistant.helpers.storage import Store
from quilt_hp.tokens import TokenStore, CachedTokens

_LOGGER = logging.getLogger(__name__)
_STORE_KEY = "quilt_hp_tokens"
_STORE_VERSION = 1


class HATokenStore:
    """TokenStore backed by HA's async JSON storage."""

    def __init__(self, hass) -> None:
        self._store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)

    async def load(self, email: str) -> CachedTokens | None:
        data = await self._store.async_load() or {}
        entry = data.get(email)
        if entry is None:
            return None
        try:
            return CachedTokens(
                id_token=entry["id_token"],
                refresh_token=entry["refresh_token"],
                expires_at=entry["expires_at"],
            )
        except KeyError:
            _LOGGER.warning("Malformed token cache for %s; will re-authenticate", email)
            return None

    async def save(self, email: str, tokens: CachedTokens) -> None:
        data = await self._store.async_load() or {}
        data[email] = {
            "id_token": tokens.id_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
        }
        await self._store.async_save(data)
```

For the `TokenStore` protocol definition, see [Token management reference](../reference/token-management.md).

---

## Device and entity modeling

Before writing entity classes, you need a clear mental model of which API objects become HA *devices* and which become *entities* under those devices.

### Why Spaces are not HA devices

A `Space` is a logical zone (room) in the Quilt data model. It carries the writable HVAC state — mode, setpoints, occupancy timeouts — but it has no serial number, no hardware model identifier, and no physical form. Home Assistant's device registry is designed for physical hardware that can be identified by manufacturer, model, and serial number.

The Quilt mobile app does not differentiate between a room and its indoor unit: controlling the room and controlling the head unit are the same action. Use `snapshot.rooms` (which filters to leaf spaces only — those with a `parent_space_id`) when setting up entities. Never create entities for floor-level or home-level parent spaces.

### IDU and QSM share one HA device

The `QuiltSmartModule` (QSM) is embedded inside the `IndoorUnit` enclosure — users never see it as a separate piece of hardware. Because the Quilt app presents them as one unit and the QSM has no user-visible serial number, map them to a **single HA device** identified by the IDU's hardware identifiers.

Use `snapshot.qsm_for_idu(idu)` to resolve the QSM for a given IDU when you need radar or ambient-light sensor data.

```python
from homeassistant.helpers.entity import DeviceInfo

DOMAIN = "quilt_hp"

def idu_device_info(idu, snapshot) -> DeviceInfo:
    """Build HA DeviceInfo for an IDU (and its embedded QSM)."""
    space = next(
        s for s in snapshot.rooms if s.id == idu.space_id
    )
    return DeviceInfo(
        identifiers={(DOMAIN, idu.id)},
        name=space.name,          # room name, e.g. "Living Room"
        manufacturer="Quilt",
        model=idu.settings.name or "Indoor Unit",
        serial_number=None,       # serial_number not currently exposed via API
    )
```

The `climate` entity for the room belongs to this device. It reads setpoint and mode from `Space.controls` and writes via `client.set_space()`, but it is registered as a child of the IDU device because the IDU is the physical hardware.

### Controller (Quilt Dial) as a separate linked device

The Quilt Dial (`Controller`) is physically separate from the IDU — it is a standalone circular thermostat with its own Wi-Fi radio, temperature sensor, and display. It is associated with the same `space_id` as the IDU it works with, but it has its own serial number and model SKU.

Create a **separate HA device** for each Dial, linked to the IDU device for the same space using `via_device`:

```python
def controller_device_info(ctrl, snapshot) -> DeviceInfo:
    """Build HA DeviceInfo for a Quilt Dial (Controller)."""
    # Find the IDU in the same space so we can set via_device.
    idu = next(
        (u for u in snapshot.indoor_units if u.space_id == ctrl.space_id),
        None,
    )
    return DeviceInfo(
        identifiers={(DOMAIN, ctrl.id)},
        name=ctrl.name or "Quilt Dial",
        manufacturer="Quilt",
        model=ctrl.model_sku or "Dial",
        serial_number=ctrl.serial_number,
        via_device=(DOMAIN, idu.id) if idu else None,
    )
```

`via_device` tells HA that the Dial is physically associated with (and accessed through) the IDU device, which correctly groups them in the HA UI by room.

### Entity-to-object mapping

| HA platform | Entity name example | Source model | Key fields | Writable? |
|-------------|---------------------|--------------|------------|-----------|
| `climate` | Living Room | `Space.controls` + `IndoorUnit.controls` | `hvac_mode`, `heating_setpoint_c`, `cooling_setpoint_c`, `fan_speed` | Yes — `client.set_space()` / `client.set_indoor_unit()` |
| `sensor` (temperature) | Living Room Temperature | `IndoorUnit.state` | `ambient_temperature_c` | No |
| `sensor` (humidity) | Living Room Humidity | `IndoorUnit.state` | `ambient_humidity_percent` | No |
| `binary_sensor` (presence) | Living Room Presence | `IndoorUnit.presence_detected` | OR of both radar channels | No |
| `binary_sensor` (occupancy) | Living Room Occupancy (auto-away) | `IndoorUnit.effective_occupancy_state` | `occupancy_state == OccupancyState.DETECTED` | No |
| `light` | Living Room Light | `IndoorUnit.controls` | `led_state`, `led_brightness`, `led_color_code` | Yes — `client.set_indoor_unit()` |
| `select` (fan speed) | Living Room Fan Speed | `IndoorUnit.controls` | `fan_speed` | Yes — `client.set_indoor_unit()` |
| `select` (louver) | Living Room Louver | `IndoorUnit.controls` | `louver_mode` | Yes — `client.set_indoor_unit()` |
| `sensor` (Dial temperature) | Living Room Dial Temperature | `Controller` | `ambient_temperature_c` | No |

> **Presence vs occupancy**: these are different signals — don't expose just one under an ambiguous name. `idu.presence_detected` is the **realtime** radar presence (flips within seconds; the vendor app's combined value). `idu.effective_occupancy_state` is the **derived** auto-away decision, debounced by ~3 min to set and ~20 min to clear (server defaults). Use the properties rather than reading `idu.presence` / `idu.occupancy` directly — both return `None` when the IDU is offline, avoiding stale data being presented as current.

### Resolving IDUs and Controllers for a space

A space always has at most one IDU in a typical Quilt installation. Use these patterns when setting up platforms:

```python
# All rooms (leaf spaces only — no floor/home-level spaces)
rooms = snapshot.rooms

# Map space_id → IndoorUnit (for the common single-IDU-per-room case)
idu_by_space: dict[str, IndoorUnit] = {
    idu.space_id: idu for idu in snapshot.indoor_units
}

# Map space_id → Controller (Dial), if one is installed in that room
ctrl_by_space: dict[str, Controller] = {
    ctrl.space_id: ctrl for ctrl in snapshot.controllers
}

# Resolve the QSM embedded in an IDU
qsm = snapshot.qsm_for_idu(idu)  # returns QuiltSmartModule | None
```

---

## Step 2: Build the coordinator

```python
from __future__ import annotations
import logging
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from quilt_hp import QuiltClient
from quilt_hp.models.controller import Controller
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.space import Space
from quilt_hp.models.system import SystemSnapshot

_LOGGER = logging.getLogger(__name__)


class QuiltCoordinator(DataUpdateCoordinator[SystemSnapshot]):
    def __init__(self, hass, email: str, token_store) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Quilt HP",
            update_interval=timedelta(minutes=5),
        )
        self._client = QuiltClient(email, token_store=token_store)
        self._stream = None

    async def async_setup(self) -> None:
        await self._client.__aenter__()
        await self._client.login()
        snapshot = await self._client.get_snapshot()
        self.async_set_updated_data(snapshot)
        await self._start_stream(snapshot)

    async def _start_stream(self, snapshot: SystemSnapshot) -> None:
        topics = snapshot.stream_topics()
        self._stream = self._client.stream(topics, max_reconnects=-1)
        # Space updates drive climate entity state (mode, setpoints, occupancy).
        self._stream.on_space_update(self._on_space_update)
        # IDU updates drive temperature/humidity sensors, fan speed, LED, and
        # presence binary sensor.
        self._stream.on_indoor_unit_update(self._on_idu_update)
        # Controller updates drive Dial temperature sensor entities.
        self._stream.on_controller_update(self._on_controller_update)
        # QSM updates provide raw radar and ALS diagnostic sensor data.
        self._stream.on_qsm_update(self._on_qsm_update)
        self._stream.on_disconnected(lambda: _LOGGER.warning("Quilt stream disconnected"))
        await self._stream.start()

    def _on_space_update(self, space: Space) -> None:
        if self.data is not None:
            self.data.apply_space(space)
            self.async_set_updated_data(self.data)

    def _on_idu_update(self, idu: IndoorUnit) -> None:
        if self.data is not None:
            self.data.apply_indoor_unit(idu)
            self.async_set_updated_data(self.data)

    def _on_controller_update(self, ctrl: Controller) -> None:
        if self.data is not None:
            self.data.apply_controller(ctrl)
            self.async_set_updated_data(self.data)

    def _on_qsm_update(self, qsm: QuiltSmartModule) -> None:
        if self.data is not None:
            self.data.apply_qsm(qsm)
            self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> SystemSnapshot:
        try:
            return await self._client.get_snapshot()
        except Exception as err:
            raise UpdateFailed(f"Error fetching Quilt snapshot: {err}") from err

    async def async_shutdown(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
        await self._client.__aexit__(None, None, None)
```

---

## Step 3: Create the climate entity

The climate entity reads mode and setpoints from the `Space` but is registered under the IDU device. The `device_info` property links it to the physical hardware in the HA device registry.

```python
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode as HAHVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from quilt_hp.models.enums import HVACMode as QHVACMode

DOMAIN = "quilt_hp"

_MODE_MAP: dict[QHVACMode, HAHVACMode] = {
    QHVACMode.STANDBY: HAHVACMode.OFF,
    QHVACMode.COOL: HAHVACMode.COOL,
    QHVACMode.HEAT: HAHVACMode.HEAT,
    QHVACMode.AUTO: HAHVACMode.HEAT_COOL,
    QHVACMode.FAN: HAHVACMode.FAN_ONLY,
    QHVACMode.DRY: HAHVACMode.DRY,  # v1.0.26: dehumidification mode
}

_HA_TO_QUILT: dict[HAHVACMode, QHVACMode] = {v: k for k, v in _MODE_MAP.items()}


class QuiltClimateEntity(ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    )
    _attr_hvac_modes = list(_MODE_MAP.values())

    def __init__(self, coordinator, space_id: str, idu_id: str) -> None:
        self._coordinator = coordinator
        self._space_id = space_id
        self._idu_id = idu_id

    @property
    def space(self):
        return next(s for s in self._coordinator.data.spaces if s.id == self._space_id)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._idu_id)},
            name=self.space.name,
            manufacturer="Quilt",
            model="Indoor Unit",
        )

    @property
    def name(self) -> str:
        return self.space.name

    @property
    def unique_id(self) -> str:
        # Keyed on space_id because the climate entity represents the room,
        # not the physical IDU.
        return f"quilt_climate_{self._space_id}"

    @property
    def hvac_mode(self) -> HAHVACMode:
        return _MODE_MAP.get(self.space.controls.hvac_mode, HAHVACMode.OFF)

    @property
    def current_temperature(self) -> float | None:
        return self.space.state.ambient_temperature_c

    @property
    def target_temperature(self) -> float | None:
        mode = self.space.controls.hvac_mode
        if mode == QHVACMode.COOL:
            return self.space.controls.cooling_setpoint_c
        if mode == QHVACMode.HEAT:
            return self.space.controls.heating_setpoint_c
        return None

    @property
    def target_temperature_high(self) -> float | None:
        return self.space.controls.cooling_setpoint_c

    @property
    def target_temperature_low(self) -> float | None:
        return self.space.controls.heating_setpoint_c

    async def async_set_hvac_mode(self, hvac_mode: HAHVACMode) -> None:
        mode = _HA_TO_QUILT[hvac_mode]
        await self._coordinator._client.set_space(self.space, mode=mode)

    async def async_set_temperature(self, **kwargs) -> None:
        from homeassistant.const import ATTR_TEMPERATURE, ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW
        await self._coordinator._client.set_space(
            self.space,
            heat_setpoint_c=kwargs.get(ATTR_TARGET_TEMP_LOW),
            cool_setpoint_c=kwargs.get(ATTR_TARGET_TEMP_HIGH) or kwargs.get(ATTR_TEMPERATURE),
        )
```

---

## Step 4: Create a temperature sensor entity

The IDU temperature sensor entity is also registered under the IDU device using the same `device_info` identifiers:

```python
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo

DOMAIN = "quilt_hp"


class QuiltIndoorTempSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, idu_id: str) -> None:
        self._coordinator = coordinator
        self._idu_id = idu_id

    @property
    def idu(self):
        return next(u for u in self._coordinator.data.indoor_units if u.id == self._idu_id)

    @property
    def device_info(self) -> DeviceInfo:
        space = next(
            (s for s in self._coordinator.data.spaces if s.id == self.idu.space_id), None
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._idu_id)},
            name=space.name if space else self._idu_id,
            manufacturer="Quilt",
            model="Indoor Unit",
        )

    @property
    def name(self) -> str:
        space = next(
            (s for s in self._coordinator.data.spaces if s.id == self.idu.space_id), None
        )
        return f"{space.name} Temperature" if space else f"IDU {self._idu_id} Temperature"

    @property
    def unique_id(self) -> str:
        return f"quilt_idu_temp_{self._idu_id}"

    @property
    def native_value(self) -> float | None:
        return self.idu.state.ambient_temperature_c

    @property
    def available(self) -> bool:
        return self.idu.is_online
```

### Dial temperature sensor

Create a parallel sensor class for the `Controller` (Quilt Dial). It is registered under a **separate device** linked to the IDU device via `via_device`:

```python
from homeassistant.helpers.entity import DeviceInfo

DOMAIN = "quilt_hp"


class QuiltDialTempSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, controller_id: str) -> None:
        self._coordinator = coordinator
        self._controller_id = controller_id

    @property
    def controller(self):
        return next(
            c for c in self._coordinator.data.controllers if c.id == self._controller_id
        )

    @property
    def device_info(self) -> DeviceInfo:
        ctrl = self.controller
        # Find the IDU in the same space so we can set via_device.
        idu = next(
            (u for u in self._coordinator.data.indoor_units if u.space_id == ctrl.space_id),
            None,
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._controller_id)},
            name=ctrl.name or "Quilt Dial",
            manufacturer="Quilt",
            model=ctrl.model_sku or "Dial",
            serial_number=ctrl.serial_number,
            via_device=(DOMAIN, idu.id) if idu else None,
        )

    @property
    def name(self) -> str:
        return f"{self.controller.name or 'Quilt Dial'} Temperature"

    @property
    def unique_id(self) -> str:
        return f"quilt_dial_temp_{self._controller_id}"

    @property
    def native_value(self) -> float | None:
        return self.controller.ambient_temperature_c

    @property
    def available(self) -> bool:
        return self.controller.is_online
```

---

## Step 5: Wire up the integration entry point

```python
async def async_setup_entry(hass, entry):
    token_store = HATokenStore(hass)
    coordinator = QuiltCoordinator(hass, entry.data["email"], token_store)
    await coordinator.async_setup()

    hass.data.setdefault("quilt_hp", {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "sensor"])
    entry.async_on_unload(coordinator.async_shutdown)
    return True
```

---

## Step 6: Handle OTP authentication via a config flow

Implement a two-step flow: the user enters their email, HA triggers the OTP send, then the user enters the code.

```python
import voluptuous as vol
from homeassistant import config_entries
from quilt_hp import QuiltClient
from quilt_hp.tokens import CachedTokens

DOMAIN = "quilt_hp"


class QuiltConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: email → OTP → done."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._client: QuiltClient | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: collect email and trigger OTP send."""
        errors = {}
        if user_input is not None:
            self._email = user_input["email"]
            self._client = QuiltClient(self._email)
            try:
                # Passing no otp_callback triggers the OTP email without
                # waiting for the code — the library sends the challenge and
                # raises QuiltAuthError if the send itself fails.
                await self._client.login(otp_callback=self._send_otp)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_otp()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("email"): str}),
            errors=errors,
        )

    async def _send_otp(self, email: str) -> str:
        """Called by QuiltClient.login() to collect the OTP.

        Store the email so async_step_otp can finish the flow;
        raise an exception to pause login until the user submits the form.
        """
        # The actual OTP will come from the form in async_step_otp.
        # Raise to interrupt login — we'll resume with the code.
        raise _AwaitingOTP

    async def async_step_otp(self, user_input=None):
        """Step 2: collect OTP and complete login."""
        errors = {}
        if user_input is not None:
            otp = user_input["otp"]
            try:
                # Re-run login supplying the code directly this time.
                await self._client.login(otp_callback=lambda _: otp)
            except Exception:
                errors["base"] = "invalid_auth"
            else:
                return self.async_create_entry(
                    title=self._email,
                    data={"email": self._email},
                )

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({vol.Required("otp"): str}),
            errors=errors,
            description_placeholders={"email": self._email},
        )


class _AwaitingOTP(Exception):
    """Sentinel raised to interrupt the login coroutine while awaiting user input."""
```

The config flow stores only the email in `entry.data`. Tokens are persisted in `HATokenStore` after the first successful login and reused on subsequent HA restarts without prompting again.

When a refresh token expires, surface re-authentication by calling `self.hass.config_entries.async_start_reauth(entry)` from the coordinator's error handler.
