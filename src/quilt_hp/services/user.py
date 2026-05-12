"""UserService — current user info."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Protocol, cast

import grpc.aio

from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp._proto import quilt_services_pb2_grpc as svc_grpc
from quilt_hp.exceptions import QuiltError

logger = logging.getLogger(__name__)


class DeclaredUserType(IntEnum):
    """Declared user type used by UserAttributes."""

    UNSPECIFIED = int(svc.DECLARED_USER_TYPE_UNSPECIFIED)
    HOMEOWNER = int(svc.DECLARED_USER_TYPE_HOMEOWNER)
    PARTNER = int(svc.DECLARED_USER_TYPE_PARTNER)


@dataclass(slots=True)
class User:
    """Quilt user account."""

    id: str
    first_name: str
    last_name: str
    email: str
    phone_number: str


@dataclass(slots=True)
class UserAttributes:
    """Additional user attributes exposed by UserService."""

    declared_user_type: DeclaredUserType


class _UserServiceStub(Protocol):
    async def GetLoggedInUser(self, request: svc.GetLoggedInUserRequest) -> object: ...
    async def UpdateLoggedInUser(self, request: svc.UpdateLoggedInUserRequest) -> object: ...
    async def GetUserAttributes(self, request: svc.GetUserAttributesRequest) -> object: ...
    async def PatchUserAttributes(self, request: svc.PatchUserAttributesRequest) -> object: ...


def _to_user(response: Any) -> User:
    user = response.user if hasattr(response, "user") else response
    return User(
        id=user.quilt_user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone_number=user.phone_number,
    )


def _to_user_attributes(response: Any) -> UserAttributes:
    try:
        declared_user_type = DeclaredUserType(response.declared_user_type)
    except ValueError:
        declared_user_type = DeclaredUserType.UNSPECIFIED
    return UserAttributes(declared_user_type=declared_user_type)


class UserService:
    """Async wrapper for UserService gRPC methods."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        factory = cast("Callable[[grpc.aio.Channel], _UserServiceStub]", svc_grpc.UserServiceStub)
        self._stub: _UserServiceStub = factory(channel)

    async def get_current_user(self) -> User:
        """Get the currently authenticated user."""
        logger.debug("Getting current user")
        try:
            response = cast(
                "Any",
                await self._stub.GetLoggedInUser(svc.GetLoggedInUserRequest()),
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"GetLoggedInUser failed: {exc.details()}") from exc
        return _to_user(response)

    async def update_current_user(
        self,
        *,
        first_name: str,
        last_name: str,
        phone_number: str | None = None,
    ) -> User:
        """Update first/last name and optional phone number for current user."""
        logger.debug("Updating current user")
        try:
            response = cast(
                "Any",
                await self._stub.UpdateLoggedInUser(
                    svc.UpdateLoggedInUserRequest(
                        first_name=first_name,
                        last_name=last_name,
                        phone_number=phone_number or "",
                    )
                ),
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"UpdateLoggedInUser failed: {exc.details()}") from exc
        return _to_user(response)

    async def get_user_attributes(self) -> UserAttributes:
        """Get current user's additional attributes."""
        logger.debug("Getting user attributes")
        try:
            response = cast(
                "Any",
                await self._stub.GetUserAttributes(svc.GetUserAttributesRequest()),
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"GetUserAttributes failed: {exc.details()}") from exc
        return _to_user_attributes(response)

    async def patch_user_attributes(
        self,
        *,
        declared_user_type: DeclaredUserType,
    ) -> UserAttributes:
        """Patch user attributes for the current user."""
        logger.debug("Patching user attributes")
        try:
            response = cast(
                "Any",
                await self._stub.PatchUserAttributes(
                    svc.PatchUserAttributesRequest(
                        user_attributes=svc.UserAttributes(
                            declared_user_type=cast(
                                "svc.DeclaredUserType.ValueType",
                                int(declared_user_type),
                            ),
                        )
                    )
                ),
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"PatchUserAttributes failed: {exc.details()}") from exc
        return _to_user_attributes(response)
