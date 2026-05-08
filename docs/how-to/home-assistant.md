# Build a Home Assistant custom component

This guide walks through building a Home Assistant custom component that exposes Quilt rooms as `climate` entities with real-time updates via the streaming API.

---

## Architecture overview

A Quilt HA component uses two parts:

1. **`DataUpdateCoordinator`** — manages the `QuiltClient` connection, holds the `SystemSnapshot`, and drives entity updates.
2. **Entity classes** — translate `Space` and `IndoorUnit` models into HA platform abstractions.

The coordinator uses an initial snapshot fetch on `async_setup_entry`, then a `NotifierStream` for real-time diffs. Polling is configured as a long-TTL fallback only.

```
HA event loop
└── QuiltCoordinator (DataUpdateCoordinator)
    ├── QuiltClient (gRPC channel + token store)
    ├── SystemSnapshot  ← full state in-memory
    └── NotifierStream  ← real-time diffs → async_set_updated_data()
        └── on_space_update, on_indoor_unit_update
```

---

## Step 1 — Implement the token store

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

## Step 2 — Build the coordinator

```python
from __future__ import annotations
import logging
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from quilt_hp import QuiltClient
from quilt_hp.models.system import SystemSnapshot
from quilt_hp.models.space import Space
from quilt_hp.models.indoor_unit import IndoorUnit

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
        self._stream.on_space_update(self._on_space_update)
        self._stream.on_indoor_unit_update(self._on_idu_update)
        self._stream.on_disconnected(lambda: _LOGGER.warning("Quilt stream disconnected"))
        await self._stream.start()

    def _on_space_update(self, space: Space) -> None:
        if self.data is not None:
            self.data.spaces[space.id] = space
            self.async_set_updated_data(self.data)

    def _on_idu_update(self, idu: IndoorUnit) -> None:
        if self.data is not None:
            self.data.indoor_units[idu.id] = idu
            self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> SystemSnapshot:
        try:
            self._client.invalidate_snapshot()
            return await self._client.get_snapshot()
        except Exception as err:
            raise UpdateFailed(f"Error fetching Quilt snapshot: {err}") from err

    async def async_shutdown(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
        await self._client.__aexit__(None, None, None)
```

---

## Step 3 — Create the climate entity

```python
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode as HAHVACMode,
)
from homeassistant.const import UnitOfTemperature
from quilt_hp.models.enums import HVACMode as QHVACMode

_MODE_MAP: dict[QHVACMode, HAHVACMode] = {
    QHVACMode.STANDBY: HAHVACMode.OFF,
    QHVACMode.COOL: HAHVACMode.COOL,
    QHVACMode.HEAT: HAHVACMode.HEAT,
    QHVACMode.AUTO: HAHVACMode.HEAT_COOL,
    QHVACMode.FAN: HAHVACMode.FAN_ONLY,
}

_HA_TO_QUILT: dict[HAHVACMode, QHVACMode] = {v: k for k, v in _MODE_MAP.items()}


class QuiltClimateEntity(ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    )
    _attr_hvac_modes = list(_MODE_MAP.values())

    def __init__(self, coordinator, space_id: str) -> None:
        self._coordinator = coordinator
        self._space_id = space_id

    @property
    def space(self):
        return self._coordinator.data.spaces[self._space_id]

    @property
    def name(self) -> str:
        return self.space.name

    @property
    def unique_id(self) -> str:
        return f"quilt_space_{self._space_id}"

    @property
    def hvac_mode(self) -> HAHVACMode:
        return _MODE_MAP.get(self.space.controls.mode, HAHVACMode.OFF)

    @property
    def current_temperature(self) -> float | None:
        return self.space.state.current_temp_c

    @property
    def target_temperature(self) -> float | None:
        mode = self.space.controls.mode
        if mode == QHVACMode.COOL:
            return self.space.controls.cool_setpoint_c
        if mode == QHVACMode.HEAT:
            return self.space.controls.heat_setpoint_c
        return None

    @property
    def target_temperature_high(self) -> float | None:
        return self.space.controls.cool_setpoint_c

    @property
    def target_temperature_low(self) -> float | None:
        return self.space.controls.heat_setpoint_c

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

## Step 4 — Create a temperature sensor entity

```python
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfTemperature


class QuiltIndoorTempSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, idu_id: str) -> None:
        self._coordinator = coordinator
        self._idu_id = idu_id

    @property
    def idu(self):
        return self._coordinator.data.indoor_units[self._idu_id]

    @property
    def name(self) -> str:
        return f"IDU {self._idu_id} temperature"

    @property
    def unique_id(self) -> str:
        return f"quilt_idu_temp_{self._idu_id}"

    @property
    def native_value(self) -> float | None:
        return self.idu.state.actual_temp_c

    @property
    def available(self) -> bool:
        return self.idu.state.is_online
```

---

## Step 5 — Wire up the integration entry point

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

## OTP authentication with HA

Because HA has no interactive terminal, perform the initial OTP login outside HA using the `quilt-hp` CLI:

```bash
quilt-hp login
```

The `HATokenStore` loads those cached tokens on first setup. If re-authentication is needed later, surface an OTP prompt through a HA config flow.
