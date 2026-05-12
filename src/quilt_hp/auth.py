"""Cognito authentication — email OTP login and token refresh.

The OTP callback is injectable so that library consumers can provide their own
UI (CLI prompt, web form, etc.) without depending on stdin.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Protocol, cast

import boto3
from botocore.exceptions import ClientError

from quilt_hp.const import COGNITO_CLIENT_ID, COGNITO_REGION
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import (
    CachedTokens,
    RefreshFailureAction,
    TokenRefreshContext,
    TokenRefreshHooks,
    TokenRefreshPolicy,
    TokenRefreshReason,
    TokenStoreLike,
)

# Type for the OTP callback: receives the email, returns the OTP code.
# Supports both sync and async callables.
type OtpCallback = Callable[[str], str | Awaitable[str]]
type CognitoAuthResult = dict[str, str | int]

logger = logging.getLogger(__name__)


class _CognitoClient(Protocol):
    def initiate_auth(self, **kwargs: object) -> dict[str, object]: ...
    def respond_to_auth_challenge(self, **kwargs: object) -> dict[str, object]: ...


async def _resolve_otp(callback: OtpCallback, email: str) -> str:
    """Call the OTP callback, handling both sync and async variants."""
    result = callback(email)
    if isinstance(result, str):
        return result
    return await result


def _require_str(result: CognitoAuthResult, key: str) -> str:
    value = result.get(key)
    if isinstance(value, str):
        return value
    raise QuiltAuthError(f"Authentication response missing valid {key!r}.")


def _expires_in_s(result: CognitoAuthResult) -> int:
    value = result.get("ExpiresIn")
    if isinstance(value, int):
        return value
    logger.warning("Authentication response missing valid ExpiresIn; using default")
    return 3600


def _make_cognito_client() -> _CognitoClient:
    """Create a boto3 Cognito Identity Provider client."""
    return cast(
        "_CognitoClient",
        boto3.client("cognito-idp", region_name=COGNITO_REGION),
    )


async def _do_otp_login(email: str, otp_callback: OtpCallback) -> CognitoAuthResult:
    """Full OTP flow. Returns Cognito AuthenticationResult dict."""
    loop = asyncio.get_running_loop()
    cognito = await loop.run_in_executor(None, _make_cognito_client)

    # Step 1: Initiate CUSTOM_AUTH
    try:
        resp = await loop.run_in_executor(
            None,
            partial(
                cognito.initiate_auth,
                AuthFlow="CUSTOM_AUTH",
                AuthParameters={"USERNAME": email},
                ClientId=COGNITO_CLIENT_ID,
                ClientMetadata={},
            ),
        )
    except ClientError as exc:
        error = exc.response["Error"]
        raise QuiltAuthError(f"Auth failed [{error['Code']}]: {error['Message']}") from exc

    if resp.get("ChallengeName") != "CUSTOM_CHALLENGE":
        raise QuiltAuthError(f"Unexpected challenge: {resp.get('ChallengeName')}")

    session = resp.get("Session")
    if not isinstance(session, str):
        raise QuiltAuthError("Authentication challenge missing valid Session.")

    # Step 2: Get OTP from the caller
    otp = await _resolve_otp(otp_callback, email)

    # Step 3: Respond to challenge
    try:
        resp2 = await loop.run_in_executor(
            None,
            partial(
                cognito.respond_to_auth_challenge,
                ClientId=COGNITO_CLIENT_ID,
                ChallengeName="CUSTOM_CHALLENGE",
                Session=session,
                ChallengeResponses={"USERNAME": email, "ANSWER": otp},
                ClientMetadata={},
            ),
        )
    except ClientError as exc:
        error = exc.response["Error"]
        raise QuiltAuthError(
            f"OTP challenge failed [{error['Code']}]: {error['Message']}"
        ) from exc

    auth_result = resp2.get("AuthenticationResult")
    if not isinstance(auth_result, dict):
        raise QuiltAuthError("Authentication response missing AuthenticationResult.")
    return cast("CognitoAuthResult", auth_result)


async def _do_refresh(refresh_token: str) -> CognitoAuthResult:
    """Use a refresh token to get a new IdToken."""
    loop = asyncio.get_running_loop()
    cognito = await loop.run_in_executor(None, _make_cognito_client)
    try:
        resp = await loop.run_in_executor(
            None,
            partial(
                cognito.initiate_auth,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
                ClientId=COGNITO_CLIENT_ID,
            ),
        )
        auth_result = resp.get("AuthenticationResult")
        if not isinstance(auth_result, dict):
            raise QuiltAuthError("Refresh response missing AuthenticationResult.")
        return cast("CognitoAuthResult", auth_result)
    except ClientError as exc:
        error = exc.response["Error"]
        raise QuiltAuthError(
            f"Token refresh failed [{error['Code']}]: {error['Message']}"
        ) from exc


async def _load_tokens(token_store: TokenStoreLike, email: str) -> CachedTokens | None:
    load = token_store.load
    if inspect.iscoroutinefunction(load):
        return await cast("Callable[[str], Awaitable[CachedTokens | None]]", load)(email)
    sync_load = cast("Callable[[str], CachedTokens | None]", load)
    return await asyncio.to_thread(sync_load, email)


async def _save_tokens(token_store: TokenStoreLike, email: str, tokens: CachedTokens) -> None:
    save = token_store.save
    if inspect.iscoroutinefunction(save):
        await cast(
            "Callable[[str, CachedTokens], Awaitable[None]]",
            save,
        )(email, tokens)
        return
    sync_save = cast("Callable[[str, CachedTokens], None]", save)
    await asyncio.to_thread(sync_save, email, tokens)


async def authenticate(
    email: str,
    otp_callback: OtpCallback | None = None,
    token_store: TokenStoreLike | None = None,
    *,
    refresh_context: TokenRefreshContext | None = None,
    refresh_hooks: TokenRefreshHooks | None = None,
    refresh_policy: TokenRefreshPolicy | None = None,
) -> str:
    """Return a valid Cognito IdToken (JWT) for the given email.

    1. If *token_store* has a valid cached token → return it.
    2. If *token_store* has a refresh token → use REFRESH_TOKEN_AUTH.
    3. Fall back to the full OTP flow (requires *otp_callback*).

    Token persistence is delegated to *token_store*. Pass ``None`` for
    purely in-memory/stateless operation (caller handles caching).
    """
    now = time.time()
    cached = await _load_tokens(token_store, email) if token_store else None

    # 1. Valid cached IdToken
    if cached is not None and not cached.is_expired:
        logger.debug("Using cached token")
        return cached.id_token

    # 2. Refresh token
    if cached is not None and cached.refresh_token:
        logger.debug("Starting token refresh")
        context = refresh_context or TokenRefreshContext(
            reason=TokenRefreshReason.EXPIRED_CACHED_TOKEN,
            source="authenticate",
        )
        if refresh_hooks is not None:
            await refresh_hooks.on_refresh_start(context)
        try:
            result = await _do_refresh(cached.refresh_token)
        except (QuiltAuthError, ClientError) as exc:
            if refresh_hooks is not None:
                await refresh_hooks.on_refresh_failure(context, exc)
            action = (
                refresh_policy.on_refresh_failure(context, exc)
                if refresh_policy is not None
                else RefreshFailureAction.FALLBACK_TO_OTP
            )
            if action == RefreshFailureAction.RAISE or otp_callback is None:
                raise
            logger.warning("Refresh failed; falling back to OTP")
        else:
            tokens = CachedTokens(
                id_token=_require_str(result, "IdToken"),
                refresh_token=cached.refresh_token,
                expires_at=now + _expires_in_s(result),
            )
            if token_store:
                await _save_tokens(token_store, email, tokens)
            if refresh_hooks is not None:
                await refresh_hooks.on_refresh_success(context, tokens)
            logger.info("Token refresh succeeded")
            return tokens.id_token

    # 3. Full OTP login
    if otp_callback is None:
        raise QuiltAuthError(
            "No valid cached token and no otp_callback provided. "
            "Call authenticate() with an otp_callback to perform the "
            "OTP login flow."
        )

    result = await _do_otp_login(email, otp_callback)
    tokens = CachedTokens(
        id_token=_require_str(result, "IdToken"),
        refresh_token=_require_str(result, "RefreshToken") if "RefreshToken" in result else "",
        expires_at=now + _expires_in_s(result),
    )
    if token_store:
        await _save_tokens(token_store, email, tokens)
    logger.info("OTP login succeeded")
    return tokens.id_token
