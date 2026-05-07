"""High-level async client for the Quilt HVAC cloud API.

Usage::

    async with QuiltClient("user@example.com") as client:
        await client.login(
            otp_callback=lambda email: input(f"OTP for {email}: ")
        )
        spaces = await client.list_spaces()
        for space in spaces:
            print(f"{space.name}: {space.state.ambient_temperature_c}°C")
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self

from quilt_hp.auth import OtpCallback, authenticate
from quilt_hp.const import Environment
from quilt_hp.exceptions import QuiltAuthError, QuiltError
from quilt_hp.services.hds import HomeDatastoreService
from quilt_hp.services.streaming import NotifierStream
from quilt_hp.services.system import SystemInformationService
from quilt_hp.services.user import DeclaredUserType, User, UserAttributes, UserService
from quilt_hp.tokens import (
    TokenRefreshContext,
    TokenRefreshHooks,
    TokenRefreshPolicy,
    TokenRefreshReason,
    TokenStoreLike,
)
from quilt_hp.transport import auth_metadata, create_channel

if TYPE_CHECKING:
    from datetime import datetime

    import grpc.aio

    from quilt_hp.models.comfort import ComfortSetting
    from quilt_hp.models.energy import SpaceEnergyMetrics
    from quilt_hp.models.enums import FanSpeed, HVACMode, LouverMode
    from quilt_hp.models.indoor_unit import IndoorUnit
    from quilt_hp.models.schedule import ScheduleDay, ScheduleEvent, ScheduleWeek, ScheduleWeekDay
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemInfo, SystemSnapshot


class QuiltClient:
    """Async client for the Quilt HVAC cloud API.

    Manages authentication, gRPC channel lifecycle, and exposes high-level
    methods for controlling Quilt mini-split systems.

    Args:
        email: Quilt account email address.
        home: Optional home name filter (substring match) for multi-home
            accounts.
        environment: API environment (default: PROD).
        snapshot_ttl_s: If > 0, cache the system snapshot for this many
            seconds. Useful for read-heavy integrations. Default: 0
            (no cache).
    """

    def __init__(
        self,
        email: str,
        *,
        home: str | None = None,
        environment: Environment = Environment.PROD,
        snapshot_ttl_s: float = 0,
        token_store: TokenStoreLike | None = None,
        token_refresh_hooks: TokenRefreshHooks | None = None,
        token_refresh_policy: TokenRefreshPolicy | None = None,
    ) -> None:
        self._email = email
        self._home = home
        self._environment = environment
        self._snapshot_ttl_s = snapshot_ttl_s
        self._token_store = token_store
        self._token_refresh_hooks = token_refresh_hooks
        self._token_refresh_policy = token_refresh_policy
        self._token: str | None = None
        self._channel: grpc.aio.Channel | None = None
        self._system_id: str | None = None
        self._system_name: str | None = None  # name of the resolved system

        # Service instances (lazily created after login)
        self._hds: HomeDatastoreService | None = None
        self._sysinfo: SystemInformationService | None = None
        self._user_svc: UserService | None = None

        # Snapshot cache
        self._snapshot_cache: SystemSnapshot | None = None
        self._snapshot_cached_at: float = 0.0

    def get_current_token(self) -> str:
        """Token provider callable for the transport interceptor."""
        if self._token is None:
            raise QuiltAuthError("Not authenticated. Call login() first.")
        return self._token

    def _ensure_channel(self) -> grpc.aio.Channel:
        if self._channel is None:
            self._channel = create_channel(
                self,
                self._environment,
                refresh_callback=self.refresh_token,
            )
            self._hds = HomeDatastoreService(self._channel)
            self._sysinfo = SystemInformationService(self._channel)
            self._user_svc = UserService(self._channel)
        return self._channel

    # --- Auth ---

    async def login(self, otp_callback: OtpCallback | None = None) -> None:
        """Authenticate with the Quilt API.

        If cached tokens are valid, no OTP is needed. Otherwise, the
        otp_callback is called to obtain the OTP code sent to the user's email.

        Args:
            otp_callback: Callable that receives the email and returns the OTP.
                          Can be sync or async.
        """
        self._token = await authenticate(
            self._email,
            otp_callback,
            self._token_store,
            refresh_hooks=self._token_refresh_hooks,
            refresh_policy=self._token_refresh_policy,
        )
        self._ensure_channel()

    async def refresh_token(self, context: TokenRefreshContext | None = None) -> None:
        """Refresh the auth token without OTP when refresh token is valid."""
        resolved_context = context or TokenRefreshContext(
            reason=TokenRefreshReason.EXPIRED_CACHED_TOKEN,
            source="client",
        )
        self._token = await authenticate(
            self._email,
            token_store=self._token_store,
            refresh_context=resolved_context,
            refresh_hooks=self._token_refresh_hooks,
            refresh_policy=self._token_refresh_policy,
        )

    # --- System discovery ---

    @property
    def system_name(self) -> str | None:
        """Name of the resolved system after get_system_id() is called."""
        return self._system_name

    async def list_systems(self) -> list[SystemInfo]:
        """List all systems the user has access to."""
        self._ensure_channel()
        assert self._sysinfo is not None
        return await self._sysinfo.list_systems()

    async def get_system_id(self, home: str | None = None) -> str:
        """Get primary system ID, cached after first call unless home changes."""
        target_home = home or self._home
        if self._system_id is not None:
            # Bypass the cache only when a different home is requested.
            if not home or home == self._home:
                return self._system_id

        systems = await self.list_systems()
        if not systems:
            raise QuiltError("No systems found for this account.")

        if target_home:
            matches = [s for s in systems if target_home.lower() in s.name.lower()]
            if not matches:
                names = [s.name for s in systems]
                raise QuiltError(f"No home matching {target_home!r}. Available: {names}")
            self._system_id = matches[0].id
            self._system_name = matches[0].name
        else:
            # No home filter — use the first system (primary home)
            self._system_id = systems[0].id
            self._system_name = systems[0].name

        return self._system_id

    async def get_snapshot(self, system_id: str | None = None) -> SystemSnapshot:
        """Fetch a full system snapshot.

        If ``snapshot_ttl_s`` was set on the client and the cached snapshot is
        still fresh, the cached copy is returned without a network round-trip.
        Pass ``system_id`` to query a specific system (bypasses and does not
        populate the cache for the default system).
        """
        self._ensure_channel()
        assert self._hds is not None
        sid = system_id or await self.get_system_id()

        # Only use cache for the default (unspecified) system_id
        if system_id is None and self._snapshot_ttl_s > 0:
            age = time.monotonic() - self._snapshot_cached_at
            if self._snapshot_cache is not None and age < self._snapshot_ttl_s:
                return self._snapshot_cache

        snapshot = await self._hds.get_system(sid)

        if system_id is None and self._snapshot_ttl_s > 0:
            self._snapshot_cache = snapshot
            self._snapshot_cached_at = time.monotonic()

        return snapshot

    def invalidate_snapshot(self) -> None:
        """Discard the cached snapshot so the next call fetches fresh data."""
        self._snapshot_cache = None
        self._snapshot_cached_at = 0.0

    # --- Space control ---

    async def list_spaces(self) -> list[Space]:
        """List all room-level spaces (excludes the root home space)."""
        snapshot = await self.get_snapshot()
        return snapshot.rooms

    async def set_space(
        self,
        space: Space | str,
        *,
        mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
    ) -> Space:
        """Update a space's HVAC mode and/or setpoints.

        Args:
            space: A ``Space`` object (no snapshot lookup needed) **or** a
                   space ID string (snapshot is fetched to resolve the object).
        """
        self._ensure_channel()
        assert self._hds is not None
        if isinstance(space, str):
            snapshot = await self.get_snapshot()
            resolved = next((s for s in snapshot.spaces if s.id == space), None)
            if resolved is None:
                raise QuiltError(f"Space {space!r} not found")
            space = resolved
        return await self._hds.update_space(
            space,
            mode=mode,
            heat_setpoint_c=heat_setpoint_c,
            cool_setpoint_c=cool_setpoint_c,
        )

    async def set_space_settings(
        self,
        space: Space | str,
        *,
        unoccupied_timeout_s: float | None = None,
        occupied_timeout_s: float | None = None,
    ) -> Space:
        """Update a space's auto-away / auto-return timeouts.

        Args:
            space: A ``Space`` object or space ID string.
            unoccupied_timeout_s: Seconds of no-presence before auto-away.
            occupied_timeout_s: Seconds of presence before auto-return.
        """
        self._ensure_channel()
        assert self._hds is not None
        if isinstance(space, str):
            snapshot = await self.get_snapshot()
            resolved = next((s for s in snapshot.spaces if s.id == space), None)
            if resolved is None:
                raise QuiltError(f"Space {space!r} not found")
            space = resolved
        return await self._hds.update_space_settings(
            space,
            unoccupied_timeout_s=unoccupied_timeout_s,
            occupied_timeout_s=occupied_timeout_s,
        )

    # --- Indoor unit control ---

    async def list_indoor_units(self) -> list[IndoorUnit]:
        """List all indoor units."""
        snapshot = await self.get_snapshot()
        return snapshot.indoor_units

    async def set_indoor_unit(
        self,
        idu: IndoorUnit | str,
        *,
        fan_speed: FanSpeed | None = None,
        louver_mode: LouverMode | None = None,
        louver_position: float | None = None,
        led_color_code: int | None = None,
        led_brightness: float | None = None,
        led_animation: int | None = None,
    ) -> IndoorUnit:
        """Update indoor unit controls.

        Args:
            idu: An ``IndoorUnit`` object (no snapshot lookup needed) **or** an
                 IDU ID string (snapshot is fetched to resolve the object).
        """
        self._ensure_channel()
        assert self._hds is not None
        if isinstance(idu, str):
            snapshot = await self.get_snapshot()
            resolved = next((u for u in snapshot.indoor_units if u.id == idu), None)
            if resolved is None:
                raise QuiltError(f"Indoor unit {idu!r} not found")
            idu = resolved
        return await self._hds.update_indoor_unit(
            idu,
            fan_speed=fan_speed,
            louver_mode=louver_mode,
            louver_position=louver_position,
            led_color_code=led_color_code,
            led_brightness=led_brightness,
            led_animation=led_animation,
        )

    async def set_indoor_unit_settings(
        self,
        idu: IndoorUnit | str,
        *,
        fence_left_m: float | None = None,
        fence_right_m: float | None = None,
        fence_forward_m: float | None = None,
        radar_height_m: float | None = None,
        light_brightness_default: float | None = None,
    ) -> IndoorUnit:
        """Update indoor unit settings.

        Args:
            idu: An ``IndoorUnit`` object **or** an IDU ID string.
            fence_left_m: Left boundary of presence detection zone in metres.
            fence_right_m: Right boundary of presence detection zone in metres.
            fence_forward_m: Forward boundary of detection zone in metres.
            radar_height_m: Radar sensor mounting height from floor in metres.
            light_brightness_default: Default LED brightness (0.0–1.0).

        All parameters are optional; omitted fields keep their current value.
        Set a fence value to 0.0 to clear it (returns to max-range detection).
        """
        self._ensure_channel()
        assert self._hds is not None
        if isinstance(idu, str):
            snapshot = await self.get_snapshot()
            resolved = next((u for u in snapshot.indoor_units if u.id == idu), None)
            if resolved is None:
                raise QuiltError(f"Indoor unit {idu!r} not found")
            idu = resolved
        return await self._hds.update_indoor_unit_settings(
            idu,
            fence_left_m=fence_left_m,
            fence_right_m=fence_right_m,
            fence_forward_m=fence_forward_m,
            radar_height_m=radar_height_m,
            light_brightness_default=light_brightness_default,
        )

    async def list_comfort_settings(self) -> list[ComfortSetting]:
        """List all comfort presets."""
        snapshot = await self.get_snapshot()
        return snapshot.comfort_settings

    async def update_comfort_setting(
        self,
        setting: ComfortSetting | str,
        *,
        name: str | None = None,
        hvac_mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
        fan_speed: FanSpeed | None = None,
    ) -> ComfortSetting:
        """Update a comfort setting preset.

        Args:
            setting: A ``ComfortSetting`` object (no snapshot lookup needed)
                **or** a setting ID string (snapshot resolves the object).
        """
        self._ensure_channel()
        assert self._hds is not None
        if isinstance(setting, str):
            snapshot = await self.get_snapshot()
            resolved = next((s for s in snapshot.comfort_settings if s.id == setting), None)
            if resolved is None:
                raise QuiltError(f"Comfort setting {setting!r} not found")
            setting = resolved
        return await self._hds.update_comfort_setting(
            setting,
            name=name,
            hvac_mode=hvac_mode,
            heat_setpoint_c=heat_setpoint_c,
            cool_setpoint_c=cool_setpoint_c,
            fan_speed=fan_speed,
        )

    # --- Schedules ---

    async def create_schedule_day(
        self,
        space_id: str,
        name: str,
        events: list[ScheduleEvent],
    ) -> ScheduleDay:
        """Create a new schedule day program from domain schedule events."""
        self._ensure_channel()
        assert self._hds is not None
        system_id = await self.get_system_id()
        return await self._hds.create_schedule_day(
            system_id=system_id,
            space_id=space_id,
            name=name,
            events=events,
        )

    async def create_schedule_week(
        self,
        space_id: str,
        days: list[ScheduleWeekDay] | None = None,
    ) -> ScheduleWeek:
        """Create a new schedule week from domain weekday mappings."""
        self._ensure_channel()
        assert self._hds is not None
        system_id = await self.get_system_id()
        return await self._hds.create_schedule_week(
            system_id=system_id,
            space_id=space_id,
            days=days,
        )

    async def update_schedule_week(
        self,
        schedule_week_id: str,
        space_id: str,
        days: list[ScheduleWeekDay],
    ) -> ScheduleWeek:
        """Update an existing schedule week with domain weekday mappings."""
        self._ensure_channel()
        assert self._hds is not None
        system_id = await self.get_system_id()
        return await self._hds.update_schedule_week(
            schedule_week_id=schedule_week_id,
            system_id=system_id,
            space_id=space_id,
            days=days,
        )

    async def delete_schedule_day(self, schedule_day_id: str) -> None:
        """Delete a schedule day program."""
        self._ensure_channel()
        assert self._hds is not None
        await self._hds.delete_schedule_day(schedule_day_id)

    async def update_schedule_day(
        self,
        schedule_day_id: str,
        space_id: str,
        name: str | None = None,
        events: list[ScheduleEvent] | None = None,
    ) -> ScheduleDay:
        """Update an existing schedule day using domain schedule events."""
        self._ensure_channel()
        assert self._hds is not None
        system_id = await self.get_system_id()
        return await self._hds.update_schedule_day(
            schedule_day_id=schedule_day_id,
            system_id=system_id,
            space_id=space_id,
            name=name,
            events=events,
        )

    async def delete_schedule_week(self, schedule_week_id: str) -> None:
        """Delete a schedule week."""
        self._ensure_channel()
        assert self._hds is not None
        await self._hds.delete_schedule_week(schedule_week_id)

    async def set_schedule_execution(self, paused: bool) -> None:
        """Globally pause or resume all schedules for the primary location.

        Args:
            paused: True to pause all schedules, False to resume.
        """
        self._ensure_channel()
        assert self._hds is not None
        snapshot = await self.get_snapshot()
        loc = snapshot.primary_location
        if loc is None:
            raise QuiltError("No location found for this system.")
        await self._hds.update_location_schedule_execution(
            location_id=loc.id,
            system_id=loc.system_id,
            paused=paused,
        )

    # --- Energy ---

    async def get_energy(
        self,
        start: datetime,
        end: datetime,
        system_id: str | None = None,
    ) -> list[SpaceEnergyMetrics]:
        """Fetch energy metrics for a time range."""
        self._ensure_channel()
        assert self._sysinfo is not None
        sid = system_id or await self.get_system_id()
        return await self._sysinfo.get_energy_metrics(sid, start, end)

    # --- Streaming ---

    def stream(
        self,
        topics: list[str],
        *,
        max_reconnects: int = -1,
        reconnect_delay_s: float = 1.0,
    ) -> NotifierStream:
        """Create a NotifierStream for real-time updates.

        Args:
            topics: List of topic strings to subscribe to
                    (e.g. ``["hds/space/<uuid>"]``).
            max_reconnects: Maximum automatic reconnects per disconnect. ``-1``
                means unlimited (the default).
            reconnect_delay_s: Initial back-off in seconds before reconnecting.
                Doubles on each attempt, capped at 60 s.

        Returns a ``NotifierStream`` that can be used as:

        - **Background task** (for integrations)::

            async with client.stream(topics) as stream:
                stream.on_space_update(my_callback)
                # stream runs in background, do other work here
                await asyncio.sleep(3600)

        - **Blocking** (for CLI / scripts)::

            s = client.stream(topics)
            s.on_space_update(my_callback)
            await s.run_forever()
        """
        channel = self._ensure_channel()
        return NotifierStream.create(
            channel,
            topics,
            metadata_provider=lambda: auth_metadata(self),
            authenticate=self.refresh_token,
            max_reconnects=max_reconnects,
            reconnect_delay_s=reconnect_delay_s,
        )

    # --- User ---

    async def get_current_user(self) -> User:
        """Get the currently authenticated user."""
        self._ensure_channel()
        assert self._user_svc is not None
        return await self._user_svc.get_current_user()

    async def update_current_user(
        self,
        *,
        first_name: str,
        last_name: str,
        phone_number: str | None = None,
    ) -> User:
        """Update current user's first/last name and optional phone number."""
        self._ensure_channel()
        assert self._user_svc is not None
        return await self._user_svc.update_current_user(
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
        )

    async def get_user_attributes(self) -> UserAttributes:
        """Get current user's additional attributes."""
        self._ensure_channel()
        assert self._user_svc is not None
        return await self._user_svc.get_user_attributes()

    async def patch_user_attributes(
        self,
        *,
        declared_user_type: DeclaredUserType,
    ) -> UserAttributes:
        """Patch current user's additional attributes."""
        self._ensure_channel()
        assert self._user_svc is not None
        return await self._user_svc.patch_user_attributes(
            declared_user_type=declared_user_type,
        )

    # --- Lifecycle ---

    async def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
