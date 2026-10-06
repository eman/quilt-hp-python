"""UpdateController: rename a Dial and choose whether its room is controlled to its temperature."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.client import QuiltClient
from quilt_hp.models import RemoteSensorControlMode
from quilt_hp.services.hds import HomeDatastoreService
from tests.tui_harness import load_snapshot


def _service() -> tuple[HomeDatastoreService, AsyncMock]:
    service = HomeDatastoreService.__new__(HomeDatastoreService)
    stub = AsyncMock()
    service._stub = stub  # type: ignore[assignment]
    return service, stub


async def test_sensor_switch_sends_only_controls() -> None:
    dial = load_snapshot().controllers[0]
    service, stub = _service()
    stub.UpdateController.return_value = hds.Controller(
        header=hds.EntityMetadata(object_id=dial.id, system_id=dial.system_id),
        controls=hds.ControllerControls(
            remote_sensor_control_mode=hds.REMOTE_SENSOR_CONTROL_MODE_DISABLED
        ),
    )
    updated = await service.update_controller(dial, uses_dial_temperature=False)

    sent = stub.UpdateController.await_args.args[0].controller
    assert (sent.header.object_id, sent.header.system_id) == (dial.id, dial.system_id)
    assert sent.HasField("controls") and not sent.HasField("settings")
    assert sent.controls.remote_sensor_control_mode == hds.REMOTE_SENSOR_CONTROL_MODE_DISABLED
    assert sent.controls.updated_ts.seconds > 0
    assert updated.remote_sensor_mode is RemoteSensorControlMode.DISABLED
    assert updated.uses_dial_temperature is False


async def test_rename_echoes_the_description() -> None:
    dial = load_snapshot().controllers[0]
    dial.description = "by the door"
    service, stub = _service()
    stub.UpdateController.return_value = hds.Controller()
    await service.update_controller(dial, name="  Hall Dial ", uses_dial_temperature=True)

    sent = stub.UpdateController.await_args.args[0].controller
    assert (sent.settings.name, sent.settings.description) == ("Hall Dial", "by the door")
    assert sent.settings.updated_ts.seconds > 0
    assert sent.controls.remote_sensor_control_mode == hds.REMOTE_SENSOR_CONTROL_MODE_ENABLED


async def test_validation() -> None:
    dial = load_snapshot().controllers[0]
    service, stub = _service()
    with pytest.raises(ValueError, match="Give a name"):
        await service.update_controller(dial)
    with pytest.raises(ValueError, match="empty"):
        await service.update_controller(dial, name="  ")
    stub.UpdateController.assert_not_awaited()


async def test_client_resolves_an_id_and_refreshes_the_cache() -> None:
    snap = load_snapshot()
    dial = snap.controllers[0]
    client = QuiltClient("user@example.com")
    client.get_snapshot = AsyncMock(return_value=snap)  # type: ignore[method-assign]
    service = AsyncMock()
    service.update_controller.return_value = dial
    client._hds = service
    client._snapshot_cache = object()  # type: ignore[assignment]

    assert await client.set_controller(dial.id, uses_dial_temperature=True) is dial
    assert service.update_controller.await_args.args[0] is dial
    assert service.update_controller.await_args.kwargs == {
        "name": None,
        "uses_dial_temperature": True,
    }
    assert client._snapshot_cache is None


def test_description_survives_a_sparse_stream_diff() -> None:
    snap = load_snapshot()
    dial = snap.controllers[0]
    dial.description = "by the door"
    diff = type(dial).from_proto(
        hds.Controller(header=hds.EntityMetadata(object_id=dial.id, system_id=dial.system_id))
    )
    assert diff.description is None
    assert snap.apply_controller(diff).description == "by the door"


def test_a_dial_reporting_no_state_is_offline() -> None:
    """The server sends an offline Dial with an empty state; the app shows it offline."""
    from quilt_hp.models import Controller

    dial = Controller.from_proto(
        hds.Controller(
            header=hds.EntityMetadata(object_id="c-1", system_id="s-1"),
            state=hds.ControllerState(),
        )
    )
    assert dial.state_updated_at is None
    assert dial.is_online is False
