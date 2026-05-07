"""HomeDatastoreService — async CRUD for spaces, IDUs, comfort settings, schedules."""

from __future__ import annotations

import time

import grpc.aio
from google.protobuf.timestamp_pb2 import Timestamp

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp._proto import quilt_hds_pb2_grpc as hds_grpc
from quilt_hp.exceptions import QuiltError, QuiltNotFoundError
from quilt_hp.models.comfort import ComfortSetting
from quilt_hp.models.enums import FanSpeed, HVACMode, LouverMode
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.schedule import ScheduleDay, ScheduleWeek
from quilt_hp.models.space import Space
from quilt_hp.models.system import SystemSnapshot


def _now_ts() -> Timestamp:
    ts = Timestamp()
    ts.FromSeconds(int(time.time()))
    return ts


class HomeDatastoreService:
    """Async wrapper for HomeDatastoreService gRPC methods."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._stub = hds_grpc.HomeDatastoreServiceStub(channel)

    async def get_system(self, system_id: str) -> SystemSnapshot:
        """Fetch a full system snapshot."""
        try:
            snap = await self._stub.GetHomeDatastoreSystem(
                hds.GetHomeDatastoreSystemRequest(system_id=system_id)
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.NOT_FOUND:
                raise QuiltNotFoundError(f"System {system_id} not found") from exc
            raise QuiltError(f"GetHomeDatastoreSystem failed: {exc.details()}") from exc
        return SystemSnapshot.from_proto(snap)

    async def update_space(
        self,
        snapshot_space: Space,
        *,
        mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
    ) -> Space:
        """Update a space's HVAC mode and/or setpoints.

        Follows the app's setpoint routing rules:
        - temperature_setpoint_c = mode-relevant setpoint
        - Both heating/cooling setpoints are always sent

        STANDBY semantics:
        When mode=STANDBY is explicitly requested the comfort-setting association
        is cleared (empty id, override=NONE).  This produces plain OFF — the room
        stays off regardless of occupancy.  Sending the existing comfort_setting_id
        when going to STANDBY would preserve an AWAY setting and the room would
        still reactivate on occupancy.
        """
        c = snapshot_space.controls
        mode_enum = mode if mode is not None else c.hvac_mode
        mode_val = mode_enum.value
        heat = heat_setpoint_c if heat_setpoint_c is not None else c.heating_setpoint_c
        cool = cool_setpoint_c if cool_setpoint_c is not None else c.cooling_setpoint_c

        # Mode-relevant setpoint routing (from KX.java)
        temp_setpoint = heat if mode_enum == HVACMode.HEAT else cool

        # AUTO mode: enforce cool - heat >= 2.5°C
        if mode_enum == HVACMode.AUTO and cool - heat < 2.5:
            cool = heat + 2.5

        # Setting to STANDBY explicitly means "turn off" — clear the comfort
        # setting so occupancy cannot reactivate the room (i.e. not AWAY mode).
        if mode_enum == HVACMode.STANDBY:
            cs_id = ""
            cs_override = hds.COMFORT_SETTING_OVERRIDE_NONE
        else:
            cs_id = c.comfort_setting_id
            cs_override = hds.COMFORT_SETTING_OVERRIDE_UNTIL_NEXT_SCHEDULE

        diff = hds.Space(
            header=hds.EntityMetadata(
                object_id=snapshot_space.id,
                system_id=snapshot_space.system_id,
            ),
            controls=hds.SpaceControls(
                hvac_mode=mode_val,
                temperature_setpoint_c=temp_setpoint,
                heating_temperature_setpoint_c=heat,
                cooling_temperature_setpoint_c=cool,
                updated_ts=_now_ts(),
                comfort_setting_override=cs_override,
                comfort_setting_id_string=cs_id,
            ),
        )
        try:
            result = await self._stub.UpdateSpace(hds.UpdateSpaceRequest(diff=diff))
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateSpace failed: {exc.details()}") from exc
        return Space.from_proto(result)

    async def update_space_settings(
        self,
        snapshot_space: Space,
        *,
        unoccupied_timeout_s: float | None = None,
        occupied_timeout_s: float | None = None,
    ) -> Space:
        """Update a space's auto-away / auto-return timeouts.

        Sends a sparse UpdateSpace diff containing only the ``settings`` block.
        All current settings fields are echoed back to avoid the server clearing
        fields that are absent from a partial proto (name, timezone, etc.).
        """
        s = snapshot_space.settings
        diff = hds.Space(
            header=hds.EntityMetadata(
                object_id=snapshot_space.id,
                system_id=snapshot_space.system_id,
            ),
            settings=hds.SpaceSettings(
                name=s.name,
                timezone=s.timezone,
                occupancy=s.occupancy_mode.value,
                occupied_timeout_s=(
                    occupied_timeout_s if occupied_timeout_s is not None else s.occupied_timeout_s
                ),
                unoccupied_timeout_s=(
                    unoccupied_timeout_s
                    if unoccupied_timeout_s is not None
                    else s.unoccupied_timeout_s
                ),
                safety_heating=s.safety_heating.value,
                updated_ts=_now_ts(),
            ),
        )
        try:
            result = await self._stub.UpdateSpace(hds.UpdateSpaceRequest(diff=diff))
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateSpace settings failed: {exc.details()}") from exc
        return Space.from_proto(result)

    async def update_indoor_unit(
        self,
        idu: IndoorUnit,
        *,
        fan_speed: FanSpeed | None = None,
        louver_mode: LouverMode | None = None,
        louver_position: float | None = None,
        led_color_code: int | None = None,
        led_brightness: float | None = None,
        led_animation: int | None = None,
    ) -> IndoorUnit:
        """Update indoor unit controls (fan, louver, LED)."""
        c = idu.controls
        fan_mode_val, fan_pct = (
            fan_speed.to_wire() if fan_speed is not None else c.fan_speed.to_wire()
        )
        diff = hds.IndoorUnit(
            header=hds.EntityMetadata(
                object_id=idu.id,
                system_id=idu.system_id,
            ),
            controls=hds.IndoorUnitControls(
                updated_ts=_now_ts(),
                fan_speed_mode=fan_mode_val,
                fan_speed_percent=fan_pct,
                louver_mode=(
                    louver_mode.value if louver_mode is not None else c.louver_mode.value
                ),
                louver_fixed_position=(
                    louver_position if louver_position is not None else c.louver_fixed_position
                ),
                led_color_code=led_color_code if led_color_code is not None else c.led_color_code,
                led_color_brightness_percent=(
                    led_brightness if led_brightness is not None else c.led_brightness
                ),
                led_animation=(led_animation if led_animation is not None else c.led_animation),
            ),
        )
        try:
            result = await self._stub.UpdateIndoorUnit(hds.UpdateIndoorUnitRequest(diff=diff))
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateIndoorUnit failed: {exc.details()}") from exc
        return IndoorUnit.from_proto(result)

    async def update_indoor_unit_settings(
        self,
        idu: IndoorUnit,
        *,
        fence_left_m: float | None = None,
        fence_right_m: float | None = None,
        fence_forward_m: float | None = None,
        radar_height_m: float | None = None,
        light_brightness_default: float | None = None,
    ) -> IndoorUnit:
        """Update indoor unit settings (presence fence geometry, default brightness)."""
        st = idu.settings
        diff = hds.IndoorUnit(
            header=hds.EntityMetadata(
                object_id=idu.id,
                system_id=idu.system_id,
            ),
            settings=hds.IndoorUnitSettings(
                updated_ts=_now_ts(),
                name=st.name,
                description=st.description,
                light_brightness_default_percent=(
                    light_brightness_default
                    if light_brightness_default is not None
                    else st.light_brightness_default_percent
                ),
                presence_fence_left_m=(
                    fence_left_m if fence_left_m is not None else st.presence_fence_left_m
                ),
                presence_fence_right_m=(
                    fence_right_m if fence_right_m is not None else st.presence_fence_right_m
                ),
                presence_fence_forward_m=(
                    fence_forward_m if fence_forward_m is not None else st.presence_fence_forward_m
                ),
                radar_sensor_distance_from_floor_m=(
                    radar_height_m
                    if radar_height_m is not None
                    else st.radar_sensor_distance_from_floor_m
                ),
            ),
        )
        try:
            result = await self._stub.UpdateIndoorUnit(hds.UpdateIndoorUnitRequest(diff=diff))
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateIndoorUnit settings failed: {exc.details()}") from exc
        return IndoorUnit.from_proto(result)

    async def update_comfort_setting(
        self,
        setting: ComfortSetting,
        *,
        name: str | None = None,
        hvac_mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
        fan_speed: FanSpeed | None = None,
    ) -> ComfortSetting:
        """Update a comfort setting preset."""
        fan_mode_val, fan_pct = (
            fan_speed.to_wire() if fan_speed is not None else setting.fan_speed.to_wire()
        )
        diff = hds.ComfortSetting(
            header=hds.EntityMetadata(
                object_id=setting.id,
                system_id=setting.system_id,
            ),
            attributes=hds.ComfortSettingAttributes(
                updated_ts=_now_ts(),
                name=name if name is not None else setting.name,
                heating_temperature_setpoint_c=(
                    heat_setpoint_c if heat_setpoint_c is not None else setting.heating_setpoint_c
                ),
                cooling_temperature_setpoint_c=(
                    cool_setpoint_c if cool_setpoint_c is not None else setting.cooling_setpoint_c
                ),
                hvac_mode=(hvac_mode.value if hvac_mode is not None else setting.hvac_mode.value),
                fan_speed_mode=fan_mode_val,
                fan_speed_percent=fan_pct,
                type=setting.type.value,
            ),
        )
        try:
            result = await self._stub.UpdateComfortSetting(
                hds.UpdateComfortSettingRequest(comfort_setting=diff)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateComfortSetting failed: {exc.details()}") from exc
        return ComfortSetting.from_proto(result)

    async def create_schedule_day(
        self,
        system_id: str,
        space_id: str,
        name: str,
        events: list[hds.ScheduleEvent],
    ) -> ScheduleDay:
        """Create a new schedule day program for a space."""
        diff = hds.ScheduleDay(
            header=hds.EntityMetadata(system_id=system_id),
            attributes=hds.ScheduleDayAttributes(name=name),
            relationships=hds.ScheduleDayRelationships(space_id=space_id),
            events=events,
        )
        try:
            result = await self._stub.CreateScheduleDay(
                hds.CreateScheduleDayRequest(schedule_day=diff)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"CreateScheduleDay failed: {exc.details()}") from exc
        return ScheduleDay.from_proto(result)

    async def create_schedule_week(
        self,
        system_id: str,
        space_id: str,
        days: list[hds.ScheduleWeekDay] | None = None,
    ) -> ScheduleWeek:
        """Create a new schedule week for a space."""
        diff = hds.ScheduleWeek(
            header=hds.EntityMetadata(system_id=system_id),
            relationships=hds.ScheduleWeekRelationships(space_id=space_id),
            days=days or [],
        )
        try:
            result = await self._stub.CreateScheduleWeek(
                hds.CreateScheduleWeekRequest(schedule_week=diff)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"CreateScheduleWeek failed: {exc.details()}") from exc
        return ScheduleWeek.from_proto(result)

    async def update_schedule_week(
        self,
        schedule_week_id: str,
        system_id: str,
        space_id: str,
        days: list[hds.ScheduleWeekDay],
    ) -> ScheduleWeek:
        """Update an existing schedule week."""
        diff = hds.ScheduleWeek(
            header=hds.EntityMetadata(
                object_id=schedule_week_id,
                system_id=system_id,
            ),
            relationships=hds.ScheduleWeekRelationships(space_id=space_id),
            days=days,
        )
        try:
            result = await self._stub.UpdateScheduleWeek(
                hds.UpdateScheduleWeekRequest(schedule_week=diff)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateScheduleWeek failed: {exc.details()}") from exc
        return ScheduleWeek.from_proto(result)

    async def delete_schedule_day(self, schedule_day_id: str) -> None:
        """Delete a schedule day program."""
        try:
            await self._stub.DeleteScheduleDay(
                hds.DeleteScheduleDayRequest(schedule_day_id=schedule_day_id)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"DeleteScheduleDay failed: {exc.details()}") from exc

    async def update_schedule_day(
        self,
        schedule_day_id: str,
        system_id: str,
        space_id: str,
        name: str | None = None,
        events: list[hds.ScheduleEvent] | None = None,
    ) -> ScheduleDay:
        """Update an existing schedule day (name and/or events)."""
        diff = hds.ScheduleDay(
            header=hds.EntityMetadata(
                object_id=schedule_day_id,
                system_id=system_id,
            ),
            relationships=hds.ScheduleDayRelationships(space_id=space_id),
        )
        if name is not None:
            diff.attributes.CopyFrom(hds.ScheduleDayAttributes(name=name))
        if events is not None:
            diff.events.extend(events)  # type: ignore[attr-defined]
        try:
            result = await self._stub.UpdateScheduleDay(
                hds.UpdateScheduleDayRequest(schedule_day=diff)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateScheduleDay failed: {exc.details()}") from exc
        return ScheduleDay.from_proto(result)

    async def delete_schedule_week(self, schedule_week_id: str) -> None:
        """Delete a schedule week."""
        try:
            await self._stub.DeleteScheduleWeek(
                hds.DeleteScheduleWeekRequest(schedule_week_id=schedule_week_id)
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"DeleteScheduleWeek failed: {exc.details()}") from exc

    async def update_location_schedule_execution(
        self,
        location_id: str,
        system_id: str,
        paused: bool,
    ) -> None:
        """Pause or resume all schedules for a location (global switch).

        Args:
            paused: True to pause all schedules, False to resume.
        """
        execution = hds.SCHEDULE_EXECUTION_PAUSED if paused else hds.SCHEDULE_EXECUTION_RUNNING
        diff = hds.Location(
            header=hds.EntityMetadata(
                object_id=location_id,
                system_id=system_id,
            ),
            controls=hds.LocationControls(schedule_execution=execution),
        )
        try:
            await self._stub.UpdateLocation(hds.UpdateLocationRequest(location=diff))
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateLocation failed: {exc.details()}") from exc
