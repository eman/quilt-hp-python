"""UserService — current user info."""

from __future__ import annotations

from dataclasses import dataclass

import grpc.aio

from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp._proto import quilt_services_pb2_grpc as svc_grpc
from quilt_hp.exceptions import QuiltError


@dataclass(slots=True)
class User:
    """Quilt user account."""

    id: str
    first_name: str
    last_name: str
    email: str


class UserService:
    """Async wrapper for UserService gRPC methods."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._stub = svc_grpc.UserServiceStub(channel)

    async def get_current_user(self) -> User:
        """Get the currently authenticated user."""
        try:
            me = await self._stub.GetLoggedInUser(svc.GetLoggedInUserRequest())
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"GetLoggedInUser failed: {exc.details()}") from exc
        return User(
            id=me.quilt_user_id,
            first_name=me.first_name,
            last_name=me.last_name,
            email=me.email,
        )
