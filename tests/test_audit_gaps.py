"""Fields and read-only account APIs found in the protocol audit and added to the library."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from quilt_hp import QuiltPreconditionError
from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp.client import QuiltClient
from quilt_hp.models import (
    AccessRole,
    DataSharingSetting,
    DataSharingState,
    IndoorUnit,
    SystemSnapshot,
    UserTaskKind,
    WifiConnectionState,
)
from quilt_hp.models.qsm import WifiInfo
from quilt_hp.services import account as account_service
from tests.tui_harness import load_snapshot

# ── Hardware, creation times and Wi-Fi link details ─────────────────────────


def test_indoor_unit_reports_its_own_serial_and_its_smart_modules() -> None:
    snap = load_snapshot()
    idu = snap.indoor_units[0]
    assert idu.unit_serial_number is not None and idu.unit_serial_number.startswith("QN1-")
    assert idu.smart_module_serial_number is not None
    assert idu.smart_module_serial_number.startswith("QS1-")
    assert idu.serial_number == idu.smart_module_serial_number  # unchanged meaning
    assert idu.manufactured_at is not None and idu.created_at is not None


def test_outdoor_units_dials_rooms_and_modules_carry_hardware_and_creation_details() -> None:
    snap = load_snapshot()
    odu = snap.outdoor_units[0]
    assert odu.port_count == 2 and odu.manufactured_at is not None and odu.created_at is not None
    assert snap.controllers[0].manufactured_at is not None
    assert snap.rooms[0].created_at is not None
    assert snap.quilt_smart_modules[0].created_at is not None


def test_wifi_link_details() -> None:
    state = hds.WifiState(
        wifi_state=hds.WIFI_STATE_WPA_COMPLETED,
        ssid="HomeNet",
        signal_level_dbm=-72,
        noise_level_dbm=-92,
        rx_invalid_frag=3,
        tx_excessive_retries=1,
        ipv4_address="192.0.2.1",
    )
    wifi = WifiInfo.from_proto(state)
    assert wifi.connection_state is WifiConnectionState.COMPLETED
    assert wifi.noise_dbm == -92 and wifi.snr_db == 20
    assert (wifi.rx_invalid_fragments, wifi.tx_excessive_retries) == (3, 1)
    assert wifi.ipv6 is None
    unknown = WifiInfo.from_proto(hds.WifiState(ssid="x", wifi_state=99))  # type: ignore[arg-type]
    assert unknown.connection_state is WifiConnectionState.UNSPECIFIED and unknown.snr_db is None


def test_dial_exposes_its_full_home_wifi_link() -> None:
    dial = load_snapshot().controllers[0]
    assert dial.hosted_wifi is not None
    assert dial.hosted_wifi.ssid == dial.wifi_ssid
    assert dial.hosted_wifi.connection_state is WifiConnectionState.COMPLETED


def test_stream_diffs_keep_hardware_and_creation_details() -> None:
    """A stream diff has no hardware records or creation time; the snapshot keeps them."""
    snap = load_snapshot()
    before = snap.indoor_units[0]
    diff = IndoorUnit.from_proto(hds.IndoorUnit(header=hds.EntityMetadata(object_id=before.id)))
    assert diff.unit_serial_number is None and diff.created_at is None
    merged = snap.apply_indoor_unit(diff)
    assert merged.unit_serial_number == before.unit_serial_number
    assert merged.manufactured_at == before.manufactured_at
    assert merged.created_at == before.created_at

    odu = snap.outdoor_units[0]
    odu_diff = type(odu).from_proto(hds.OutdoorUnit(header=hds.EntityMetadata(object_id=odu.id)))
    assert snap.apply_outdoor_unit(odu_diff).port_count == odu.port_count


def test_snapshot_without_hardware_leaves_details_unknown() -> None:
    system = hds.HomeDatastoreSystem()
    system.indoor_units.add(header=hds.EntityMetadata(object_id="idu-1"))
    idu = SystemSnapshot.from_proto(system).indoor_units[0]
    assert (idu.unit_serial_number, idu.manufactured_at) == (None, None)


# ── Read-only account services ──────────────────────────────────────────────


def _account(monkeypatch: pytest.MonkeyPatch, **methods: AsyncMock) -> Any:
    stub = MagicMock(**methods)
    for name in (
        "SystemUserServiceStub",
        "InvitationServiceStub",
        "PartnerServiceStub",
        "SystemInformationServiceStub",
        "UserTaskServiceStub",
    ):
        monkeypatch.setattr(account_service.svc_grpc, name, lambda _ch, _s=stub: _s)
    return account_service.AccountService(MagicMock())


def _user(n: int) -> svc.User:
    return svc.User(
        quilt_user_id=f"u{n}", first_name="Ada", last_name=f"L{n}", email=f"a{n}@example.com"
    )


async def test_list_system_users(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = svc.ListSystemUsersResponse(
        administrators=svc.UserList(users=[_user(1), _user(2)]),
        pending_invitations=svc.InvitationList(
            invitations=[
                svc.Invitation(
                    id="inv-1",
                    invitee_email="b@example.com",
                    invited_by=svc.InviterInformation(
                        first_name="Ada", last_name="L1", email="a1@example.com"
                    ),
                    system_name="Example Home",
                    access_role=svc.ACCESS_ROLE_TO_SYSTEM_MEMBER,
                )
            ]
        ),
    )
    call = AsyncMock(return_value=reply)
    users = await _account(monkeypatch, ListSystemUsers=call).list_system_users("sys-1")
    assert call.await_args.args[0].system_id == "sys-1"
    assert [u.full_name for u in users.administrators] == ["Ada L1", "Ada L2"]
    assert users.members == []
    invite = users.pending_invitations[0]
    assert (invite.role, invite.inviter_name, invite.system_id) == (
        AccessRole.MEMBER,
        "Ada L1",
        None,
    )


async def test_access_role_and_unknown_values(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _account(
        monkeypatch,
        GetRoleOfLoggedInSystemUser=AsyncMock(
            return_value=svc.GetRoleOfLoggedInSystemUserResponse(
                access_role=svc.ACCESS_ROLE_TO_SYSTEM_ADMIN
            )
        ),
    )
    assert await service.get_access_role("sys-1") is AccessRole.ADMIN
    weird = svc.GetRoleOfLoggedInSystemUserResponse(access_role=7)  # type: ignore[arg-type]
    service._users.GetRoleOfLoggedInSystemUser = AsyncMock(return_value=weird)
    assert await service.get_access_role("sys-1") is AccessRole.UNKNOWN


async def test_partner_details_absent_for_homeowners(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _account(
        monkeypatch,
        GetLoggedInUserPartnerDetails=AsyncMock(
            return_value=svc.GetLoggedInUserPartnerDetailsResponse()
        ),
    )
    assert await service.get_partner_details() is None
    service._partners.GetLoggedInUserPartnerDetails = AsyncMock(
        return_value=svc.GetLoggedInUserPartnerDetailsResponse(
            partner_details=svc.PartnerDetails(
                partner_organization_id="org-1",
                partner_organization_name="Installers Inc",
                partner_tier="gold",
            )
        )
    )
    partner = await service.get_partner_details()
    assert partner is not None and (partner.organization_name, partner.tier) == (
        "Installers Inc",
        "gold",
    )


async def test_data_sharing(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = svc.SystemDataSharing(
        setting=svc.DATA_SHARING_SETTING_ON,
        status=svc.DataSharingStatus(state=svc.SYSTEM_DATA_SHARING_STATE_PENDING),
        partner_organization_public_profile=svc.PartnerOrganizationPublicProfile(
            partner_organization_id="org-1",
            display_name="Installers Inc",
            contact_address=svc.Address(formatted_address="1 Example St"),
        ),
    )
    reply.status.active_after.FromSeconds(1_791_000_000)
    sharing = await _account(
        monkeypatch, GetSystemDataSharing=AsyncMock(return_value=reply)
    ).get_data_sharing("s")
    assert (sharing.state, sharing.setting) == (DataSharingState.PENDING, DataSharingSetting.ON)
    assert sharing.partner is None
    assert (
        sharing.partner_profile is not None and sharing.partner_profile.address == "1 Example St"
    )
    assert sharing.active_after is not None


async def test_user_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = svc.ListUserTasksResponse(
        user_tasks=[
            svc.UserTask(
                data_sharing_consent_banner=svc.DataSharingConsentBannerTask(
                    system_id="s", system_designated_partner_organization_id="org-1"
                )
            )
        ]
    )
    tasks = await _account(
        monkeypatch, ListUserTasks=AsyncMock(return_value=reply)
    ).list_user_tasks("s")
    assert [(t.kind, t.partner_organization_id) for t in tasks] == [
        (UserTaskKind.DATA_SHARING_CONSENT_BANNER, "org-1")
    ]


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        self._code, self._details = code, details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


async def test_certified_partners_without_an_address_raise_precondition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live behaviour (2026-10-05): FAILED_PRECONDITION "system has no address"."""
    error = _FakeRpcError(grpc.StatusCode.FAILED_PRECONDITION, "system has no address")
    service = _account(monkeypatch, ListSystemCertifiedPartners=AsyncMock(side_effect=error))
    with pytest.raises(QuiltPreconditionError, match="system has no address"):
        await service.list_certified_partners("s")


async def test_client_account_methods_resolve_the_system() -> None:
    client = QuiltClient("user@example.com")
    client._system_id = "sys-1"
    account = MagicMock(
        list_system_users=AsyncMock(return_value="users"),
        get_access_role=AsyncMock(return_value=AccessRole.ADMIN),
        get_data_sharing=AsyncMock(return_value="sharing"),
        list_certified_partners=AsyncMock(return_value=[]),
        list_user_tasks=AsyncMock(return_value=[]),
        list_pending_invitations=AsyncMock(return_value=[]),
        get_partner_details=AsyncMock(return_value=None),
    )
    client._account = account
    assert await client.list_system_users() == "users"
    account.list_system_users.assert_awaited_once_with("sys-1")
    assert await client.get_access_role() is AccessRole.ADMIN
    assert await client.get_data_sharing() == "sharing"
    assert await client.list_certified_partners() == []
    assert await client.list_user_tasks() == []
    assert await client.list_pending_invitations() == []
    assert await client.get_partner_details() is None


@pytest.mark.parametrize(
    ("state", "ssid", "connected"),
    [
        (hds.WIFI_STATE_WPA_COMPLETED, "HomeNet", True),
        (hds.WIFI_STATE_SCANNING, "HomeNet", False),  # a stale network name isn't a connection
        (hds.WIFI_STATE_DISCONNECTED, "", False),
        (hds.WIFI_STATE_UNSPECIFIED, "HomeNet", True),  # payloads without a phase
    ],
)
def test_wifi_connected_follows_the_connection_phase(
    state: int, ssid: str, connected: bool
) -> None:
    wifi = WifiInfo.from_proto(hds.WifiState(wifi_state=state, ssid=ssid))  # type: ignore[arg-type]
    assert wifi.connected is connected
    assert wifi.reported


def test_disconnected_wifi_is_kept_not_dropped() -> None:
    """A Dial or module that reports DISCONNECTED (no network name) keeps its Wi-Fi record."""
    from quilt_hp.models import Controller, QuiltSmartModule

    dial = hds.Controller(header=hds.EntityMetadata(object_id="dial-1"))
    dial.hosted_wifi_state.wifi_state = hds.WIFI_STATE_DISCONNECTED
    parsed = Controller.from_proto(dial)
    assert parsed.hosted_wifi is not None
    assert parsed.hosted_wifi.connection_state is WifiConnectionState.DISCONNECTED
    assert not parsed.hosted_wifi.connected

    module = hds.QuiltSmartModule(header=hds.EntityMetadata(object_id="qsm-1"))
    module.hosted_wifi_state.wifi_state = hds.WIFI_STATE_SCANNING
    assert QuiltSmartModule.from_proto(module).hosted_wifi is not None
    # An interface that reports nothing at all is still None.
    assert QuiltSmartModule.from_proto(module).ap_wifi is None


def test_rooms_and_modules_keep_created_at_across_stream_merges() -> None:
    from quilt_hp.models import QuiltSmartModule, Space

    snap = load_snapshot()
    room, module = snap.rooms[0], snap.quilt_smart_modules[0]
    assert room.created_at is not None and module.created_at is not None
    merged_room = snap.apply_space(
        Space.from_proto(hds.Space(header=hds.EntityMetadata(object_id=room.id)))
    )
    merged_module = snap.apply_qsm(
        QuiltSmartModule.from_proto(
            hds.QuiltSmartModule(header=hds.EntityMetadata(object_id=module.id))
        )
    )
    assert merged_room.created_at == room.created_at
    assert merged_module.created_at == module.created_at


def test_account_enums_live_in_the_enums_module() -> None:
    from quilt_hp.models import account, enums

    for name in ("AccessRole", "DataSharingSetting", "DataSharingState", "UserTaskKind"):
        assert getattr(account, name) is getattr(enums, name)
