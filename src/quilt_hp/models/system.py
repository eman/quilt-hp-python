"""System-level models — system info and full snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from quilt_hp.models.comfort import ComfortSetting
from quilt_hp.models.controller import Controller
from quilt_hp.models.enums import (
    ComfortSettingType,
    HVACMode,
    LightState,
    LouverMode,
    RemoteSensorControlMode,
)
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.schedule import ScheduleDay, ScheduleWeek
from quilt_hp.models.sensor import ControllerRemoteSensor, RemoteSensor
from quilt_hp.models.software_update import SoftwareUpdateInfo
from quilt_hp.models.space import Space


@dataclass(slots=True)
class Location:
    """A Quilt location — holds global settings like schedule execution state."""

    id: str
    name: str
    system_id: str
    timezone: str
    schedule_paused: bool  # True when SCHEDULE_EXECUTION_PAUSED

    @classmethod
    def from_proto(cls, proto: object) -> Location:
        """Construct from a protobuf Location message."""
        from quilt_hp._proto import quilt_hds_pb2 as hds

        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            name=proto.attributes.name,  # type: ignore[attr-defined]
            system_id=proto.header.system_id,  # type: ignore[attr-defined]
            timezone=proto.attributes.tz_identifier,  # type: ignore[attr-defined]
            schedule_paused=(
                proto.controls.schedule_execution  # type: ignore[attr-defined]
                == hds.SCHEDULE_EXECUTION_PAUSED
            ),
        )


@dataclass(slots=True)
class SystemInfo:
    """Basic system metadata from ListSystems."""

    id: str
    name: str
    timezone: str


@dataclass(slots=True)
class SystemSnapshot:
    """Full system state from GetHomeDatastoreSystem."""

    spaces: list[Space]
    indoor_units: list[IndoorUnit]
    outdoor_units: list[OutdoorUnit]
    controllers: list[Controller]
    quilt_smart_modules: list[QuiltSmartModule]
    comfort_settings: list[ComfortSetting]
    schedule_weeks: list[ScheduleWeek]
    schedule_days: list[ScheduleDay]
    remote_sensors: list[RemoteSensor]
    controller_remote_sensors: list[ControllerRemoteSensor]
    software_update_infos: list[SoftwareUpdateInfo]
    locations: list[Location]
    timezone: str | None

    @property
    def rooms(self) -> list[Space]:
        """Return only leaf/room spaces (those with a parent)."""
        return [s for s in self.spaces if s.is_room]

    @property
    def primary_location(self) -> Location | None:
        """The first (and typically only) Location for this system."""
        return self.locations[0] if self.locations else None

    def space_by_name(self, name: str) -> Space | None:
        """Find a space by name (case-insensitive)."""
        name_lower = name.lower()
        for s in self.spaces:
            if s.name.lower() == name_lower:
                return s
        return None

    def enrich_space(self, space: Space) -> Space:
        """Resolve active_comfort_setting_type on a stream-updated Space.

        Stream updates deliver individual Space protos without the comfort
        settings context.  Call this before using space.is_away / space.is_off
        on a space received from the NotifierStream.
        """
        cs_id = space.controls.comfort_setting_id
        for cs in self.comfort_settings:
            if cs.id == cs_id:
                space.active_comfort_setting_type = cs.type
                return space
        space.active_comfort_setting_type = None
        return space

    def apply_space(self, space: Space) -> Space:
        """Enrich and patch a stream-updated Space into the snapshot.

        Resolves comfort-setting type (needed for is_away / is_off) then
        merges the diff into the existing Space, preserving sub-messages that
        were absent from the sparse proto diff.  Returns the merged space.

        Proto3 stream diffs are sparse — only changed fields are sent.  A
        settings-only diff produces a Space with ``controls.hvac_mode=UNSPECIFIED``
        and ``state.ambient_temperature_c=None``.  Without merging, those default
        values would overwrite real data.
        """
        self.enrich_space(space)
        for i, s in enumerate(self.spaces):
            if s.id == space.id:
                from dataclasses import replace

                updates: dict[str, object] = {}
                # state absent: ambient_temperature_c is None (set only when updated_ts present)
                if (
                    space.state.ambient_temperature_c is None
                    and s.state.ambient_temperature_c is not None
                ):
                    updates["state"] = s.state
                # controls absent: hvac_mode is UNSPECIFIED and existing mode is real
                if (
                    space.controls.hvac_mode == HVACMode.UNSPECIFIED
                    and s.controls.hvac_mode != HVACMode.UNSPECIFIED
                ):
                    updates["controls"] = s.controls
                # settings absent: name is empty (settings.name is always non-empty in a real Space)
                if not space.settings.name and s.settings.name:
                    updates["settings"] = s.settings
                    updates["name"] = s.name
                if updates:
                    space = replace(space, **updates)
                self.spaces[i] = space
                return space
        self.spaces.append(space)
        return space

    def apply_indoor_unit(self, idu: IndoorUnit) -> IndoorUnit:
        """Patch a stream-updated IndoorUnit into the snapshot.

        Stream protos are partial — ``qsm_id``, ``outdoor_unit_id``, the
        ``hvac_inputs``/``conditions`` sub-messages, and the ``state`` sub-message
        may all be absent in a diff.  Preserve existing values so stream updates
        don't erase them.

        In particular, a controls-only diff (e.g. LED toggle) omits ``state``,
        which would make ``state.updated_at=None`` and therefore ``is_online=False``,
        causing ``led_on`` and ``effective_occupancy_state`` to report stale data.
        """
        for i, u in enumerate(self.indoor_units):
            if u.id == idu.id:
                from dataclasses import replace

                updates: dict[str, object] = {}
                if idu.qsm_id is None and u.qsm_id:
                    updates["qsm_id"] = u.qsm_id
                if idu.outdoor_unit_id is None and u.outdoor_unit_id:
                    updates["outdoor_unit_id"] = u.outdoor_unit_id
                if idu.hvac_inputs is None and u.hvac_inputs is not None:
                    updates["hvac_inputs"] = u.hvac_inputs
                if idu.conditions is None and u.conditions is not None:
                    updates["conditions"] = u.conditions
                # state absent from diff: updated_at is None — preserve existing so is_online stays valid
                if idu.state.updated_at is None and u.state.updated_at is not None:
                    updates["state"] = u.state
                # controls absent detection: state IS in diff (has a timestamp → state-only update)
                # and all control sentinel fields are at proto3 defaults.  When controls are genuinely
                # sent: led_color_code is non-zero, OR led_state is explicit ON/OFF, OR
                # louver_mode is set.  Brightness alone is not a safe sentinel because when
                # mobile_led_scheduling_enabled is on, brightness is preserved when LED is OFF.
                if (
                    idu.state.updated_at is not None
                    and idu.controls.fan_speed_mode_raw == 0
                    and idu.controls.louver_mode == LouverMode.UNSPECIFIED
                    and idu.controls.led_color_code == 0
                    and idu.controls.led_state == LightState.UNSPECIFIED
                    and idu.controls.led_brightness == 0.0
                ):
                    updates["controls"] = u.controls
                # | None sub-messages: absent from diff → parsed as None; preserve existing data
                if idu.performance_data is None and u.performance_data is not None:
                    updates["performance_data"] = u.performance_data
                if idu.performance_metrics is None and u.performance_metrics is not None:
                    updates["performance_metrics"] = u.performance_metrics
                if idu.presence is None and u.presence is not None:
                    updates["presence"] = u.presence
                if idu.occupancy is None and u.occupancy is not None:
                    updates["occupancy"] = u.occupancy
                if updates:
                    idu = replace(idu, **updates)
                self.indoor_units[i] = idu
                return idu
        self.indoor_units.append(idu)
        return idu

    def apply_outdoor_unit(self, odu: OutdoorUnit) -> OutdoorUnit:
        """Patch a stream-updated OutdoorUnit into the snapshot.

        Stream diffs may omit ``state`` (only performance_data changed) or lack
        hardware info (no hw_map available at parse time).  Preserve any
        existing non-default values so a partial update doesn't erase them.
        """
        from dataclasses import replace

        for i, u in enumerate(self.outdoor_units):
            if u.id == odu.id:
                # Preserve hvac_state when stream diff has a default-zero state
                if not odu.hvac_state and u.hvac_state:
                    odu = replace(odu, hvac_state=u.hvac_state)
                # Preserve hardware info — stream diffs are parsed without hw_map
                if odu.model_sku is None and u.model_sku is not None:
                    odu = replace(
                        odu,
                        model_sku=u.model_sku,
                        serial_number=u.serial_number,
                        firmware_version=u.firmware_version,
                    )
                self.outdoor_units[i] = odu
                return odu
        self.outdoor_units.append(odu)
        return odu

    def apply_controller(self, ctrl: Controller) -> Controller:
        """Patch a stream-updated Controller into the snapshot.

        Stream diffs are sparse — a temperature state diff omits settings (name)
        and hosted_wifi_state.  Preserve existing non-empty values.
        Hardware info (serial, model_sku, firmware_version) is only populated at
        initial snapshot load and is never in stream diffs; always preserve it.
        """
        from dataclasses import replace

        for i, c in enumerate(self.controllers):
            if c.id == ctrl.id:
                updates: dict[str, object] = {}
                if not ctrl.name and c.name:
                    updates["name"] = c.name
                if ctrl.wifi_ssid is None and c.wifi_ssid is not None:
                    updates["wifi_ssid"] = c.wifi_ssid
                    updates["wifi_ip"] = c.wifi_ip
                    updates["wifi_signal_dbm"] = c.wifi_signal_dbm
                    updates["wifi_freq_mhz"] = c.wifi_freq_mhz
                    updates["wifi_last_seen"] = c.wifi_last_seen
                if ctrl.ap_wifi is None and c.ap_wifi is not None:
                    updates["ap_wifi"] = c.ap_wifi
                if ctrl.p2p_wifi is None and c.p2p_wifi is not None:
                    updates["p2p_wifi"] = c.p2p_wifi
                if (
                    ctrl.remote_sensor_mode == RemoteSensorControlMode.UNSPECIFIED
                    and c.remote_sensor_mode != RemoteSensorControlMode.UNSPECIFIED
                ):
                    updates["remote_sensor_mode"] = c.remote_sensor_mode
                # Hardware fields are never in stream diffs — always preserve from snapshot
                if ctrl.serial_number is None and c.serial_number is not None:
                    updates["serial_number"] = c.serial_number
                    updates["model_sku"] = c.model_sku
                    updates["firmware_version"] = c.firmware_version
                if updates:
                    ctrl = replace(ctrl, **updates)
                self.controllers[i] = ctrl
                return ctrl
        self.controllers.append(ctrl)
        return ctrl

    def apply_qsm(self, qsm: QuiltSmartModule) -> QuiltSmartModule:
        """Patch a stream-updated QuiltSmartModule into the snapshot.

        Stream diffs are sparse — a controls diff omits state (sensors) and wifi
        state sub-messages.  Preserve existing non-None values.
        """
        from dataclasses import replace

        for i, q in enumerate(self.quilt_smart_modules):
            if q.id == qsm.id:
                updates: dict[str, object] = {}
                if qsm.sensors is None and q.sensors is not None:
                    updates["sensors"] = q.sensors
                if qsm.hosted_wifi is None and q.hosted_wifi is not None:
                    updates["hosted_wifi"] = q.hosted_wifi
                if qsm.ap_wifi is None and q.ap_wifi is not None:
                    updates["ap_wifi"] = q.ap_wifi
                if qsm.p2p_wifi is None and q.p2p_wifi is not None:
                    updates["p2p_wifi"] = q.p2p_wifi
                if updates:
                    qsm = replace(qsm, **updates)
                self.quilt_smart_modules[i] = qsm
                return qsm
        self.quilt_smart_modules.append(qsm)
        return qsm

    def apply_remote_sensor(self, rs: RemoteSensor) -> RemoteSensor:
        """Patch a stream-updated RemoteSensor into the snapshot.

        Stream diffs are sparse — a state-only diff (temperature/humidity update)
        omits controls, leaving control_mode=UNSPECIFIED.  A controls-only diff
        omits state, zeroing all sensor readings.  Preserve existing non-None values.
        """
        from dataclasses import replace

        for i, r in enumerate(self.remote_sensors):
            if r.id == rs.id:
                updates: dict[str, object] = {}
                # controls absent: control_mode defaults to UNSPECIFIED
                if (
                    rs.control_mode == RemoteSensorControlMode.UNSPECIFIED
                    and r.control_mode != RemoteSensorControlMode.UNSPECIFIED
                ):
                    updates["control_mode"] = r.control_mode
                # state absent: all sensor readings become None
                if rs.ambient_temperature_c is None and r.ambient_temperature_c is not None:
                    updates["ambient_temperature_c"] = r.ambient_temperature_c
                if rs.humidity_percent is None and r.humidity_percent is not None:
                    updates["humidity_percent"] = r.humidity_percent
                if rs.battery_level_percent is None and r.battery_level_percent is not None:
                    updates["battery_level_percent"] = r.battery_level_percent
                if rs.signal_level_dbm is None and r.signal_level_dbm is not None:
                    updates["signal_level_dbm"] = r.signal_level_dbm
                if updates:
                    rs = replace(rs, **updates)
                self.remote_sensors[i] = rs
                return rs
        self.remote_sensors.append(rs)
        return rs

    def apply_controller_remote_sensor(
        self, crs: ControllerRemoteSensor
    ) -> ControllerRemoteSensor:
        """Patch a stream-updated ControllerRemoteSensor into the snapshot (sparse-diff safe)."""
        from dataclasses import replace

        for i, r in enumerate(self.controller_remote_sensors):
            if r.id == crs.id:
                updates: dict[str, object] = {}
                if (
                    crs.control_mode == RemoteSensorControlMode.UNSPECIFIED
                    and r.control_mode != RemoteSensorControlMode.UNSPECIFIED
                ):
                    updates["control_mode"] = r.control_mode
                if crs.ambient_temperature_c is None and r.ambient_temperature_c is not None:
                    updates["ambient_temperature_c"] = r.ambient_temperature_c
                if crs.humidity_percent is None and r.humidity_percent is not None:
                    updates["humidity_percent"] = r.humidity_percent
                if crs.battery_level_percent is None and r.battery_level_percent is not None:
                    updates["battery_level_percent"] = r.battery_level_percent
                if crs.signal_level_dbm is None and r.signal_level_dbm is not None:
                    updates["signal_level_dbm"] = r.signal_level_dbm
                if updates:
                    crs = replace(crs, **updates)
                self.controller_remote_sensors[i] = crs
                return crs
        self.controller_remote_sensors.append(crs)
        return crs

    def qsm_for_idu(self, idu: IndoorUnit) -> QuiltSmartModule | None:
        """Return the QSM embedded in the given IDU, or None."""
        if not idu.qsm_id:
            return None
        return next((q for q in self.quilt_smart_modules if q.id == idu.qsm_id), None)

    def stream_topics(self) -> list[str]:
        """Return the NotifierService topic strings for this snapshot.

        Pass the result directly to ``client.stream(topics)``.  Covers all
        rooms, indoor units, outdoor units, and controllers.
        """
        topics: list[str] = []
        for space in self.rooms:
            topics.append(f"hds/space/{space.id}")
        for idu in self.indoor_units:
            topics.append(f"hds/indoor_unit/{idu.id}")
        for odu in self.outdoor_units:
            topics.append(f"hds/outdoor_unit/{odu.id}")
        for ctrl in self.controllers:
            topics.append(f"hds/controller/{ctrl.id}")
        for qsm in self.quilt_smart_modules:
            topics.append(f"hds/quilt_smart_module/{qsm.id}")
        for rs in self.remote_sensors:
            topics.append(f"hds/remote_sensor/{rs.id}")
        for crs in self.controller_remote_sensors:
            topics.append(f"hds/controller_remote_sensor/{crs.id}")
        for sui in self.software_update_infos:
            topics.append(f"hds/software_update_info/{sui.id}")
        return topics

    @classmethod
    def from_proto(cls, proto: object) -> SystemSnapshot:
        """Construct from a protobuf HomeDatastoreSystem message."""
        odu_hw_map = {
            h.header.object_id: h
            for h in proto.outdoor_unit_hardware  # type: ignore[attr-defined]
        }
        ctrl_hw_map = {
            h.header.object_id: h
            for h in proto.controller_hardware  # type: ignore[attr-defined]
        }

        locations = [Location.from_proto(loc) for loc in proto.locations]  # type: ignore[attr-defined]
        tz = locations[0].timezone if locations else None

        comfort_settings = [
            ComfortSetting.from_proto(cs)
            for cs in proto.comfort_settings  # type: ignore[attr-defined]
        ]
        cs_type_by_id: dict[str, ComfortSettingType] = {cs.id: cs.type for cs in comfort_settings}

        spaces: list[Space] = []
        for s in proto.spaces:  # type: ignore[attr-defined]
            space = Space.from_proto(s)
            space.active_comfort_setting_type = cs_type_by_id.get(
                space.controls.comfort_setting_id
            )
            spaces.append(space)

        return cls(
            spaces=spaces,
            indoor_units=[IndoorUnit.from_proto(u) for u in proto.indoor_units],  # type: ignore[attr-defined]
            outdoor_units=[OutdoorUnit.from_proto(u, odu_hw_map) for u in proto.outdoor_units],  # type: ignore[attr-defined]
            controllers=[Controller.from_proto(c, ctrl_hw_map) for c in proto.controllers],  # type: ignore[attr-defined]
            quilt_smart_modules=[
                QuiltSmartModule.from_proto(q) for q in proto.quilt_smart_modules
            ],  # type: ignore[attr-defined]
            comfort_settings=comfort_settings,
            schedule_weeks=[ScheduleWeek.from_proto(w) for w in proto.schedule_weeks],  # type: ignore[attr-defined]
            schedule_days=[ScheduleDay.from_proto(d) for d in proto.schedule_days],  # type: ignore[attr-defined]
            remote_sensors=[RemoteSensor.from_proto(rs) for rs in proto.remote_sensors],  # type: ignore[attr-defined]
            controller_remote_sensors=[
                ControllerRemoteSensor.from_proto(crs) for crs in proto.controller_remote_sensors
            ],  # type: ignore[attr-defined]
            software_update_infos=[
                SoftwareUpdateInfo.from_proto(s) for s in proto.software_update_infos
            ],  # type: ignore[attr-defined]
            locations=locations,
            timezone=tz,
        )
