from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from quilt_hp.client import QuiltClient
from quilt_hp.exceptions import QuiltAuthError, QuiltError
from quilt_hp.services import system as system_service
from quilt_hp.services import user as user_service
from quilt_hp.services.user import DeclaredUserType


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


@pytest.mark.asyncio
async def test_client_error_and_service_wrapper_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_create_channel(*_args: object, **_kwargs: object) -> object:
        channel = MagicMock()
        channel.close = AsyncMock()
        return channel

    monkeypatch.setattr("quilt_hp.client.create_channel", _fake_create_channel)
    monkeypatch.setattr("quilt_hp.client.HomeDatastoreService", lambda _ch: MagicMock())
    monkeypatch.setattr("quilt_hp.client.SystemInformationService", lambda _ch: MagicMock())
    monkeypatch.setattr("quilt_hp.client.UserService", lambda _ch: MagicMock())

    client = QuiltClient("user@example.com")
    fake_channel = MagicMock()
    fake_channel.close = AsyncMock()
    client._channel = fake_channel

    with pytest.raises(QuiltAuthError):
        client.get_current_token()

    client._token = "jwt"
    assert client.get_current_token() == "jwt"

    client._sysinfo = MagicMock(list_systems=AsyncMock(return_value=[]))
    with pytest.raises(QuiltError, match="No systems"):
        await client.get_system_id()

    client._sysinfo = MagicMock(
        list_systems=AsyncMock(return_value=[SimpleNamespace(id="sys-1", name="Home")])
    )
    with pytest.raises(QuiltError, match="No home matching"):
        await client.get_system_id(home="Cabin")

    client._hds = MagicMock(get_system=AsyncMock(return_value=SimpleNamespace(rooms=[])))
    client._snapshot_ttl_s = 1
    await client.get_snapshot()
    client.invalidate_snapshot()

    client._hds.create_schedule_week = AsyncMock(return_value="week")
    assert await client.create_schedule_week("space-1") == "week"

    client._hds.delete_schedule_day = AsyncMock()
    await client.delete_schedule_day("day-1")
    client._hds.delete_schedule_day.assert_called_once_with("day-1")

    client._hds.delete_schedule_week = AsyncMock()
    await client.delete_schedule_week("week-1")
    client._hds.delete_schedule_week.assert_called_once_with("week-1")

    client._sysinfo = MagicMock(get_energy_metrics=AsyncMock(return_value=["energy"]))
    got = await client.get_energy(datetime.now(tz=UTC), datetime.now(tz=UTC), system_id="sys-1")
    assert got == ["energy"]

    client._user_svc = MagicMock(get_current_user=AsyncMock(return_value="me"))
    assert await client.get_current_user() == "me"
    client._user_svc.update_current_user = AsyncMock(return_value="updated")
    assert (
        await client.update_current_user(first_name="A", last_name="B", phone_number="123")
        == "updated"
    )
    client._user_svc.get_user_attributes = AsyncMock(return_value="attrs")
    assert await client.get_user_attributes() == "attrs"
    client._user_svc.patch_user_attributes = AsyncMock(return_value="patched")
    assert (
        await client.patch_user_attributes(declared_user_type=DeclaredUserType.HOMEOWNER)
        == "patched"
    )

    refreshed: list[object] = []

    async def _fake_authenticate(*_args: object, **kwargs: object) -> str:
        refreshed.append(kwargs.get("refresh_context"))
        return "new-token"

    monkeypatch.setattr("quilt_hp.client.authenticate", _fake_authenticate)
    await client.refresh_token()
    assert client.get_current_token() == "new-token"
    assert refreshed and refreshed[0] is not None

    stream = client.stream(["hds/space/space-1"])
    assert stream is not None

    await client.close()
    assert fake_channel.close.await_count == 1


@pytest.mark.asyncio
async def test_client_requires_login_and_close_clears_services() -> None:
    client = QuiltClient("user@example.com")

    with pytest.raises(QuiltError, match=r"Client not connected\. Call login\(\) first\."):
        await client.list_systems()
    with pytest.raises(QuiltError, match=r"Client not connected\. Call login\(\) first\."):
        await client.get_snapshot()
    with pytest.raises(QuiltError, match=r"Client not connected\. Call login\(\) first\."):
        await client.get_current_user()
    with pytest.raises(QuiltError, match=r"Client not connected\. Call login\(\) first\."):
        client.stream(["hds/space/space-1"])

    fake_channel = MagicMock()
    fake_channel.close = AsyncMock()
    client._channel = fake_channel
    client._hds = MagicMock()
    client._sysinfo = MagicMock()
    client._user_svc = MagicMock()

    await client.close()

    fake_channel.close.assert_awaited_once()
    assert client._channel is None
    assert client._hds is None
    assert client._sysinfo is None
    assert client._user_svc is None


@pytest.mark.asyncio
async def test_client_wrapper_methods_and_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("quilt_hp.client.authenticate", AsyncMock(return_value="jwt-token"))

    def _fake_create_channel(*_args: object, **_kwargs: object) -> object:
        channel = MagicMock()
        channel.close = AsyncMock()
        return channel

    monkeypatch.setattr("quilt_hp.client.create_channel", _fake_create_channel)
    monkeypatch.setattr("quilt_hp.client.HomeDatastoreService", lambda _ch: MagicMock())
    monkeypatch.setattr("quilt_hp.client.SystemInformationService", lambda _ch: MagicMock())
    monkeypatch.setattr("quilt_hp.client.UserService", lambda _ch: MagicMock())

    client = QuiltClient("user@example.com")
    await client.login()

    snap = SimpleNamespace(
        spaces=[SimpleNamespace(id="space-1"), SimpleNamespace(id="space-2")],
        rooms=[SimpleNamespace(id="space-1"), SimpleNamespace(id="space-2")],
        indoor_units=[SimpleNamespace(id="idu-1"), SimpleNamespace(id="idu-2")],
        comfort_settings=[SimpleNamespace(id="comfort-1"), SimpleNamespace(id="comfort-2")],
    )
    client._hds = MagicMock(
        update_space_settings=AsyncMock(return_value="space-settings"),
        update_indoor_unit_settings=AsyncMock(return_value="idu-settings"),
        update_comfort_setting=AsyncMock(return_value="comfort"),
        create_schedule_day=AsyncMock(return_value="day"),
        update_schedule_day=AsyncMock(return_value="day-updated"),
        update_schedule_week=AsyncMock(return_value="week-updated"),
        create_schedule_week=AsyncMock(return_value="week-created"),
        get_system=AsyncMock(return_value=snap),
    )
    client._user_svc = MagicMock(
        update_current_user=AsyncMock(return_value="user-updated"),
        get_user_attributes=AsyncMock(return_value="attrs"),
        patch_user_attributes=AsyncMock(return_value="patched"),
    )
    client._system_id = "sys-1"

    assert await client.list_spaces() == snap.rooms
    assert await client.list_indoor_units() == snap.indoor_units
    assert await client.list_comfort_settings() == snap.comfort_settings
    assert await client.set_space_settings("space-2", occupied_timeout_s=10) == "space-settings"
    assert await client.set_indoor_unit_settings("idu-2", fence_left_m=1.0) == "idu-settings"
    assert await client.update_comfort_setting("comfort-2", name="new") == "comfort"
    assert await client.create_schedule_day("space-1", "weekday", []) == "day"
    assert await client.update_schedule_day("day-1", "space-1", name="renamed") == "day-updated"
    assert await client.update_schedule_week("week-1", "space-1", []) == "week-updated"
    assert await client.create_schedule_week("space-1", []) == "week-created"
    assert await client.update_current_user(first_name="Jane", last_name="Doe") == "user-updated"
    assert await client.get_user_attributes() == "attrs"
    assert (
        await client.patch_user_attributes(declared_user_type=DeclaredUserType.PARTNER)
        == "patched"
    )

    async with client:
        assert client.get_current_token() == "jwt-token"

    assert client._channel is None
    assert client._hds is None
    assert client._sysinfo is None
    assert client._user_svc is None


@pytest.mark.asyncio
async def test_system_service_success_and_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_stub = MagicMock()
    ok_stub.ListSystems = AsyncMock(
        return_value=SimpleNamespace(
            systems=[SimpleNamespace(id="sys-1", name="Home", tz_identifier="UTC")]
        )
    )

    start_ts = system_service.Timestamp()
    start_ts.FromSeconds(10)
    end_ts = system_service.Timestamp()
    end_ts.FromSeconds(20)
    ok_stub.GetEnergyMetrics = AsyncMock(
        return_value=SimpleNamespace(
            space_energy_metrics=[
                SimpleNamespace(
                    space_id="space-1",
                    energy_buckets=[
                        SimpleNamespace(start_time=start_ts, energy_kwh=1.0, status=1),
                        SimpleNamespace(start_time=end_ts, energy_kwh=0.5, status=1),
                    ],
                )
            ]
        )
    )

    monkeypatch.setattr(
        system_service.svc_grpc, "SystemInformationServiceStub", lambda _c: ok_stub
    )
    svc = system_service.SystemInformationService(MagicMock())
    systems = await svc.list_systems()
    assert systems[0].id == "sys-1"

    metrics = await svc.get_energy_metrics(
        "sys-1",
        datetime.fromtimestamp(0, tz=UTC),
        datetime.fromtimestamp(3600, tz=UTC),
    )
    assert metrics[0].space_id == "space-1"
    assert len(metrics[0].buckets) == 2
    assert metrics[0].buckets[0].status == system_service.MetricBucketStatus.COMPLETE

    err_stub = MagicMock(
        ListSystems=AsyncMock(side_effect=_FakeRpcError(grpc.StatusCode.UNKNOWN, "x"))
    )
    monkeypatch.setattr(
        system_service.svc_grpc, "SystemInformationServiceStub", lambda _c: err_stub
    )
    svc_err = system_service.SystemInformationService(MagicMock())
    with pytest.raises(QuiltError, match="ListSystems failed"):
        await svc_err.list_systems()


@pytest.mark.asyncio
async def test_user_service_success_and_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_stub = MagicMock()
    ok_stub.GetLoggedInUser = AsyncMock(
        return_value=SimpleNamespace(
            user=SimpleNamespace(
                quilt_user_id="u-1",
                first_name="A",
                last_name="B",
                email="a@example.com",
                phone_number="+15555550123",
            )
        )
    )
    ok_stub.UpdateLoggedInUser = AsyncMock(
        return_value=SimpleNamespace(
            user=SimpleNamespace(
                quilt_user_id="u-1",
                first_name="Ada",
                last_name="Lovelace",
                email="a@example.com",
                phone_number="+15555550000",
            )
        )
    )
    ok_stub.GetUserAttributes = AsyncMock(
        return_value=SimpleNamespace(declared_user_type=int(DeclaredUserType.HOMEOWNER))
    )
    ok_stub.PatchUserAttributes = AsyncMock(
        return_value=SimpleNamespace(declared_user_type=int(DeclaredUserType.PARTNER))
    )
    monkeypatch.setattr(user_service.svc_grpc, "UserServiceStub", lambda _c: ok_stub)
    svc = user_service.UserService(MagicMock())
    user = await svc.get_current_user()
    assert user.id == "u-1"
    assert user.phone_number == "+15555550123"
    updated = await svc.update_current_user(
        first_name="Ada",
        last_name="Lovelace",
        phone_number="+15555550000",
    )
    assert updated.first_name == "Ada"
    attrs = await svc.get_user_attributes()
    assert attrs.declared_user_type == DeclaredUserType.HOMEOWNER
    patched = await svc.patch_user_attributes(declared_user_type=DeclaredUserType.PARTNER)
    assert patched.declared_user_type == DeclaredUserType.PARTNER

    err_stub = MagicMock()
    err_stub.GetLoggedInUser = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.INTERNAL, "nope")
    )
    err_stub.UpdateLoggedInUser = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.INTERNAL, "nope")
    )
    err_stub.GetUserAttributes = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.INTERNAL, "nope")
    )
    err_stub.PatchUserAttributes = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.INTERNAL, "nope")
    )
    monkeypatch.setattr(user_service.svc_grpc, "UserServiceStub", lambda _c: err_stub)
    svc_err = user_service.UserService(MagicMock())
    with pytest.raises(QuiltError, match="GetLoggedInUser failed"):
        await svc_err.get_current_user()
    with pytest.raises(QuiltError, match="UpdateLoggedInUser failed"):
        await svc_err.update_current_user(first_name="A", last_name="B")
    with pytest.raises(QuiltError, match="GetUserAttributes failed"):
        await svc_err.get_user_attributes()
    with pytest.raises(QuiltError, match="PatchUserAttributes failed"):
        await svc_err.patch_user_attributes(declared_user_type=DeclaredUserType.HOMEOWNER)
