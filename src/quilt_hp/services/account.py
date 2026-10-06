"""Read-only account services: system users, invitations, partners, data sharing, user tasks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp._proto import quilt_services_pb2_grpc as svc_grpc
from quilt_hp.models._helpers import enum_or
from quilt_hp.models.account import (
    AccessRole,
    Invitation,
    PartnerDetails,
    PartnerProfile,
    SystemDataSharing,
    SystemUsers,
    UserTask,
)
from quilt_hp.services import grpc_call

if TYPE_CHECKING:
    import grpc.aio

logger = logging.getLogger(__name__)


class AccountService:
    """Async wrappers for the read-only account RPCs across several app services."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        def stub(factory: object) -> Any:
            return cast("Callable[[grpc.aio.Channel], Any]", factory)(channel)

        self._users = stub(svc_grpc.SystemUserServiceStub)
        self._invitations = stub(svc_grpc.InvitationServiceStub)
        self._partners = stub(svc_grpc.PartnerServiceStub)
        self._sysinfo = stub(svc_grpc.SystemInformationServiceStub)
        self._tasks = stub(svc_grpc.UserTaskServiceStub)

    async def list_system_users(self, system_id: str) -> SystemUsers:
        """Administrators, members and pending invitations for a system."""
        async with grpc_call("ListSystemUsers"):
            reply = await self._users.ListSystemUsers(
                svc.ListSystemUsersRequest(system_id=system_id)
            )
        return SystemUsers.from_proto(reply)

    async def get_access_role(self, system_id: str) -> AccessRole:
        """The signed-in user's role in a system."""
        async with grpc_call("GetRoleOfLoggedInSystemUser"):
            reply = await self._users.GetRoleOfLoggedInSystemUser(
                svc.GetRoleOfLoggedInSystemUserRequest(system_id=system_id)
            )
        return enum_or(AccessRole, reply.access_role, AccessRole.UNKNOWN)

    async def list_pending_invitations(self) -> list[Invitation]:
        """Invitations the signed-in user has received and not yet answered."""
        async with grpc_call("ListPendingInvitationsForLoggedInUser"):
            reply = await self._invitations.ListPendingInvitationsForLoggedInUser(
                svc.ListPendingInvitationsRequest()
            )
        return [Invitation.from_proto(i) for i in reply.invitations]

    async def get_partner_details(self) -> PartnerDetails | None:
        """The installer partner the signed-in user belongs to, or None."""
        async with grpc_call("GetLoggedInUserPartnerDetails"):
            reply = await self._partners.GetLoggedInUserPartnerDetails(
                svc.GetLoggedInUserPartnerDetailsRequest()
            )
        if not reply.HasField("partner_details"):
            return None
        return PartnerDetails.from_proto(reply.partner_details)

    async def get_data_sharing(self, system_id: str) -> SystemDataSharing:
        """Whether a system shares its data with an installer partner."""
        async with grpc_call("GetSystemDataSharing"):
            reply = await self._sysinfo.GetSystemDataSharing(
                svc.GetSystemDataSharingRequest(system_id=system_id)
            )
        return SystemDataSharing.from_proto(reply)

    async def list_certified_partners(self, system_id: str) -> list[PartnerProfile]:
        """Certified installer partners that can serve a system's location.

        Raises ``QuiltPreconditionError`` when the system has no address set.
        """
        async with grpc_call("ListSystemCertifiedPartners"):
            reply = await self._sysinfo.ListSystemCertifiedPartners(
                svc.ListSystemCertifiedPartnersRequest(system_id=system_id)
            )
        return [PartnerProfile.from_proto(p) for p in reply.partners]

    async def list_user_tasks(self, system_id: str) -> list[UserTask]:
        """Tasks the app would prompt the user with for a system (e.g. data-sharing consent)."""
        async with grpc_call("ListUserTasks"):
            reply = await self._tasks.ListUserTasks(svc.ListUserTasksRequest(system_id=system_id))
        return [UserTask.from_proto(t) for t in reply.user_tasks]
