"""Single-object Get/List fetches and the system configuration version."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.client import QuiltClient
from quilt_hp.exceptions import QuiltError, QuiltNotFoundError
from quilt_hp.models import SystemSnapshot
from quilt_hp.services import hds as hds_service


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


def _service(
    monkeypatch: pytest.MonkeyPatch, **methods: AsyncMock
) -> hds_service.HomeDatastoreService:
    stub = MagicMock(**methods)
    monkeypatch.setattr(hds_service.hds_grpc, "HomeDatastoreServiceStub", lambda _ch: stub)
    return hds_service.HomeDatastoreService(MagicMock())


@pytest.mark.asyncio
async def test_get_space_sends_object_id_and_builds_model(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = hds.Space(header=hds.EntityMetadata(object_id="space-1"))
    reply.settings.name = "Dining Room"
    get = AsyncMock(return_value=reply)
    svc = _service(monkeypatch, GetSpace=get)

    space = await svc.get_space("space-1")

    assert get.await_args.args[0].object_id == "space-1"
    assert space.id == "space-1"
    assert space.name == "Dining Room"


@pytest.mark.asyncio
async def test_get_controller_builds_display_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = hds.Controller(header=hds.EntityMetadata(object_id="dial-1"))
    reply.state.view_state = hds.CONTROLLER_VIEW_STATE_GLANCE
    svc = _service(monkeypatch, GetController=AsyncMock(return_value=reply))

    ctrl = await svc.get_controller("dial-1")

    assert ctrl.id == "dial-1"
    assert ctrl.display_on is True
    assert ctrl.serial_number is None  # hardware is not part of a single Get


@pytest.mark.asyncio
async def test_list_filters_by_system(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = hds.ListIndoorUnitsResponse(
        indoor_units=[
            hds.IndoorUnit(header=hds.EntityMetadata(object_id="idu-1", system_id="sys-1")),
            hds.IndoorUnit(header=hds.EntityMetadata(object_id="idu-2", system_id="sys-1")),
        ]
    )
    lst = AsyncMock(return_value=reply)
    svc = _service(monkeypatch, ListIndoorUnits=lst)

    units = await svc.list_indoor_units("sys-1")

    assert lst.await_args.args[0].filter == 'header.system_id="sys-1"'
    assert [u.id for u in units] == ["idu-1", "idu-2"]


@pytest.mark.asyncio
async def test_get_maps_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(
        monkeypatch,
        GetScheduleWeek=AsyncMock(side_effect=_FakeRpcError(grpc.StatusCode.NOT_FOUND, "gone")),
    )
    with pytest.raises(QuiltNotFoundError):
        await svc.get_schedule_week("week-1")


@pytest.mark.asyncio
async def test_get_system_version_requests_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = hds.HomeDatastoreSystem()
    reply.metadata.version = 1_791_238_698_730_367_462
    get = AsyncMock(return_value=reply)
    svc = _service(monkeypatch, GetHomeDatastoreSystem=get)

    assert await svc.get_system_version("sys-1") == 1_791_238_698_730_367_462
    request = get.await_args.args[0]
    assert request.system_id == "sys-1"
    assert list(request.field_mask.paths) == ["metadata"]


@pytest.mark.asyncio
async def test_get_system_version_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(
        monkeypatch, GetHomeDatastoreSystem=AsyncMock(return_value=hds.HomeDatastoreSystem())
    )
    assert await svc.get_system_version("sys-1") is None


def test_snapshot_version_and_timestamp() -> None:
    system = hds.HomeDatastoreSystem()
    system.metadata.version = 1_791_238_698_730_367_462
    snap = SystemSnapshot.from_proto(system)
    assert snap.version == 1_791_238_698_730_367_462
    assert snap.version_at == datetime(2026, 10, 5, 22, 18, 18, 730367, tzinfo=UTC)

    assert SystemSnapshot.from_proto(hds.HomeDatastoreSystem()).version is None
    assert SystemSnapshot.from_proto(hds.HomeDatastoreSystem()).version_at is None


@pytest.mark.asyncio
async def test_client_wrappers_delegate() -> None:
    client = QuiltClient("user@example.com")
    client._system_id = "sys-1"
    hds_mock = MagicMock(
        get_system_version=AsyncMock(return_value=7),
        get_space=AsyncMock(return_value="space"),
        get_indoor_unit=AsyncMock(return_value="idu"),
        get_outdoor_unit=AsyncMock(return_value="odu"),
        get_controller=AsyncMock(return_value="ctrl"),
        get_quilt_smart_module=AsyncMock(return_value="qsm"),
        get_comfort_setting=AsyncMock(return_value="cs"),
        get_remote_sensor=AsyncMock(return_value="rs"),
        get_controller_remote_sensor=AsyncMock(return_value="crs"),
        get_schedule_day=AsyncMock(return_value="day"),
        get_schedule_week=AsyncMock(return_value="week"),
        get_software_update_info=AsyncMock(return_value="sui"),
    )
    client._hds = hds_mock

    assert await client.get_system_version() == 7
    hds_mock.get_system_version.assert_awaited_once_with("sys-1")
    assert await client.get_space("s") == "space"
    assert await client.get_indoor_unit("i") == "idu"
    assert await client.get_outdoor_unit("o") == "odu"
    assert await client.get_controller("c") == "ctrl"
    assert await client.get_quilt_smart_module("q") == "qsm"
    assert await client.get_comfort_setting("x") == "cs"
    assert await client.get_remote_sensor("r") == "rs"
    assert await client.get_controller_remote_sensor("cr") == "crs"
    assert await client.get_schedule_day("d") == "day"
    assert await client.get_schedule_week("w") == "week"
    assert await client.get_software_update_info("u") == "sui"
    hds_mock.get_schedule_week.assert_awaited_once_with("w")


@pytest.mark.asyncio
async def test_get_maps_permission_denied_to_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server answers PERMISSION_DENIED for an id that does not exist."""
    svc = _service(
        monkeypatch,
        GetSpace=AsyncMock(
            side_effect=_FakeRpcError(grpc.StatusCode.PERMISSION_DENIED, "Permission Denied.")
        ),
    )
    with pytest.raises(QuiltNotFoundError):
        await svc.get_space("no-such-space")


@pytest.mark.asyncio
async def test_get_other_errors_are_not_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(
        monkeypatch,
        GetSpace=AsyncMock(side_effect=_FakeRpcError(grpc.StatusCode.INVALID_ARGUMENT, "bad")),
    )
    with pytest.raises(QuiltError) as info:
        await svc.get_space("space-1")
    assert not isinstance(info.value, QuiltNotFoundError)
