"""Cognito authentication — email OTP login and token refresh.

The OTP callback is injectable so that library consumers can provide their own
UI (CLI prompt, web form, etc.) without depending on stdin.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import partial

import boto3
from botocore.exceptions import ClientError

from quilt_hp.const import COGNITO_CLIENT_ID, COGNITO_REGION
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CachedTokens, TokenStore

# Type for the OTP callback: receives the email, returns the OTP code.
# Supports both sync and async callables.
OtpCallback = Callable[[str], str | Awaitable[str]]


async def _resolve_otp(callback: OtpCallback, email: str) -> str:
    """Call the OTP callback, handling both sync and async variants."""
    result = callback(email)
    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
        return await result  # type: ignore[misc]
    return result  # type: ignore[return-value]


def _make_cognito_client() -> object:
    """Create a boto3 Cognito Identity Provider client."""
    return boto3.client("cognito-idp", region_name=COGNITO_REGION)


async def _do_otp_login(email: str, otp_callback: OtpCallback) -> dict[str, object]:
    """Full OTP flow. Returns Cognito AuthenticationResult dict."""
    loop = asyncio.get_running_loop()
    cognito = _make_cognito_client()

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

    session = resp["Session"]

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

    return resp2["AuthenticationResult"]  # type: ignore[no-any-return]


async def _do_refresh(refresh_token: str) -> dict[str, object] | None:
    """Use a refresh token to get a new IdToken. Returns None on failure."""
    loop = asyncio.get_running_loop()
    cognito = _make_cognito_client()
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
        return resp["AuthenticationResult"]  # type: ignore[no-any-return]
    except ClientError:
        return None


async def authenticate(
    email: str,
    otp_callback: OtpCallback | None = None,
    token_store: TokenStore | None = None,
) -> str:
    """Return a valid Cognito IdToken (JWT) for the given email.

    1. If *token_store* has a valid cached token → return it.
    2. If *token_store* has a refresh token → use REFRESH_TOKEN_AUTH.
    3. Fall back to the full OTP flow (requires *otp_callback*).

    Token persistence is delegated to *token_store*. Pass ``None`` for
    purely in-memory/stateless operation (caller handles caching).
    """
    now = time.time()
    cached = token_store.load(email) if token_store else None

    # 1. Valid cached IdToken
    if cached is not None and not cached.is_expired:
        return cached.id_token

    # 2. Refresh token
    if cached is not None and cached.refresh_token:
        result = await _do_refresh(cached.refresh_token)
        if result is not None:
            tokens = CachedTokens(
                id_token=result["IdToken"],  # type: ignore[arg-type]
                refresh_token=cached.refresh_token,
                expires_at=now + int(result.get("ExpiresIn", 3600)),  # type: ignore[arg-type]
            )
            if token_store:
                token_store.save(email, tokens)
            return tokens.id_token

    # 3. Full OTP login
    if otp_callback is None:
        raise QuiltAuthError(
            "No valid cached token and no otp_callback provided. "
            "Call authenticate() with an otp_callback to perform the OTP login flow."
        )

    result = await _do_otp_login(email, otp_callback)
    tokens = CachedTokens(
        id_token=result["IdToken"],  # type: ignore[arg-type]
        refresh_token=result.get("RefreshToken", ""),  # type: ignore[arg-type]
        expires_at=now + int(result.get("ExpiresIn", 3600)),  # type: ignore[arg-type]
    )
    if token_store:
        token_store.save(email, tokens)
    return tokens.id_token
