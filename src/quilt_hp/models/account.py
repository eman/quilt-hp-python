"""Account models: who can use a system, invitations, installer partners and data sharing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from quilt_hp.models._helpers import enum_or, present_submsg, timestamp_or_none
from quilt_hp.models.enums import AccessRole, DataSharingSetting, DataSharingState, UserTaskKind

__all__ = [
    "AccessRole",
    "DataSharingSetting",
    "DataSharingState",
    "Invitation",
    "PartnerDetails",
    "PartnerProfile",
    "SystemDataSharing",
    "SystemUser",
    "SystemUsers",
    "UserTask",
    "UserTaskKind",
]


@dataclass(slots=True)
class SystemUser:
    """A person with access to a system."""

    user_id: str
    first_name: str
    last_name: str
    email: str
    phone_number: str | None = None

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    @classmethod
    def from_proto(cls, proto: object) -> SystemUser:
        p = cast("Any", proto)
        return cls(
            user_id=p.quilt_user_id,
            first_name=p.first_name,
            last_name=p.last_name,
            email=p.email,
            phone_number=p.phone_number or None,
        )


@dataclass(slots=True)
class Invitation:
    """An invitation to join a system."""

    id: str
    invitee_email: str
    inviter_name: str
    inviter_email: str
    system_name: str
    role: AccessRole
    system_id: str | None = None

    @classmethod
    def from_proto(cls, proto: object) -> Invitation:
        p = cast("Any", proto)
        by = p.invited_by
        return cls(
            id=p.id,
            invitee_email=p.invitee_email,
            inviter_name=" ".join(x for x in (by.first_name, by.last_name) if x),
            inviter_email=by.email,
            system_name=p.system_name,
            role=enum_or(AccessRole, p.access_role, AccessRole.UNKNOWN),
            system_id=p.system_id or None,
        )


@dataclass(slots=True)
class SystemUsers:
    """Everyone with access to a system, and who has been invited."""

    administrators: list[SystemUser] = field(default_factory=list)
    members: list[SystemUser] = field(default_factory=list)
    pending_invitations: list[Invitation] = field(default_factory=list)

    @classmethod
    def from_proto(cls, proto: object) -> SystemUsers:
        p = cast("Any", proto)
        return cls(
            administrators=[SystemUser.from_proto(u) for u in p.administrators.users],
            members=[SystemUser.from_proto(u) for u in p.members.users],
            pending_invitations=[
                Invitation.from_proto(i) for i in p.pending_invitations.invitations
            ],
        )


@dataclass(slots=True)
class PartnerDetails:
    """An installer partner organisation."""

    organization_id: str
    organization_name: str
    tier: str | None = None

    @classmethod
    def from_proto(cls, proto: object) -> PartnerDetails | None:
        p = cast("Any", proto)
        if not p.partner_organization_id:
            return None
        return cls(
            organization_id=p.partner_organization_id,
            organization_name=p.partner_organization_name,
            tier=p.partner_tier or None,
        )


@dataclass(slots=True)
class PartnerProfile:
    """An installer partner's public contact details."""

    organization_id: str
    display_name: str
    phone_number: str | None = None
    website_url: str | None = None
    email: str | None = None
    address: str | None = None  # the formatted postal address

    @classmethod
    def from_proto(cls, proto: object) -> PartnerProfile:
        p = cast("Any", proto)
        addr = present_submsg(p, "contact_address")
        return cls(
            organization_id=p.partner_organization_id,
            display_name=p.display_name,
            phone_number=p.contact_phone_number or None,
            website_url=p.contact_website_url or None,
            email=p.contact_email_address or None,
            address=(cast("Any", addr).formatted_address or None) if addr is not None else None,
        )


@dataclass(slots=True)
class SystemDataSharing:
    """Whether a system shares data with its installer partner."""

    state: DataSharingState
    setting: DataSharingSetting = DataSharingSetting.UNSPECIFIED
    partner: PartnerDetails | None = None
    partner_profile: PartnerProfile | None = None
    active_after: datetime | None = None
    """When sharing takes effect, for a pending change."""

    @classmethod
    def from_proto(cls, proto: object) -> SystemDataSharing:
        p = cast("Any", proto)
        status = present_submsg(p, "status")
        partner = present_submsg(p, "partner")
        profile = present_submsg(p, "partner_organization_public_profile")
        return cls(
            state=enum_or(
                DataSharingState,
                cast("Any", status).state if status is not None else 0,
                DataSharingState.UNSPECIFIED,
            ),
            setting=enum_or(DataSharingSetting, p.setting, DataSharingSetting.UNSPECIFIED),
            partner=PartnerDetails.from_proto(partner) if partner is not None else None,
            partner_profile=PartnerProfile.from_proto(profile) if profile is not None else None,
            active_after=(
                timestamp_or_none(getattr(status, "active_after", None))
                if status is not None
                else None
            ),
        )


@dataclass(slots=True)
class UserTask:
    """Something the app asks the user to act on, e.g. a data-sharing consent banner."""

    kind: UserTaskKind
    system_id: str | None = None
    partner_organization_id: str | None = None

    @classmethod
    def from_proto(cls, proto: object) -> UserTask:
        banner = present_submsg(proto, "data_sharing_consent_banner")
        if banner is None:
            return cls(kind=UserTaskKind.UNSPECIFIED)
        b = cast("Any", banner)
        return cls(
            kind=UserTaskKind.DATA_SHARING_CONSENT_BANNER,
            system_id=b.system_id or None,
            partner_organization_id=b.system_designated_partner_organization_id or None,
        )
