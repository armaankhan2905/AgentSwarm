"""Explicit local trust boundary or real Supabase Auth token verification."""

from dataclasses import dataclass
from ipaddress import ip_address
from uuid import UUID

import httpx
from fastapi import HTTPException, Request

from .config import is_loopback

LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class Identity:
    id: str


async def current_user(request: Request) -> Identity:
    settings = request.app.state.settings
    if settings.auth_mode == "local":
        # Uvicorn is normally reached directly in local development. In the
        # combined image nginx is a trusted, loopback proxy and overwrites
        # X-Real-IP with the actual peer address. Never use Host or a
        # user-supplied forwarded header as the trust boundary: a remote user
        # must still be rejected when they send Host: localhost.
        if not request.client:
            raise HTTPException(403, "Local single-user mode is restricted to loopback connections")
        peer = request.client.host
        try:
            peer_address = ip_address(peer)
        except ValueError:
            raise HTTPException(403, "Local single-user mode is restricted to loopback connections") from None
        trusted_proxy = any(peer_address in network for network in settings.trusted_proxy_networks)
        real_ip = request.headers.get("x-real-ip", "").strip()
        if trusted_proxy and real_ip:
            # X-Real-IP is a single hop value. Reject lists and malformed
            # values instead of selecting an attacker-controlled entry.
            try:
                if "," in real_ip or ";" in real_ip:
                    raise ValueError
                peer = str(ip_address(real_ip))
            except ValueError:
                raise HTTPException(403, "Invalid trusted proxy client address") from None
        if not is_loopback(peer):
            raise HTTPException(403, "Local single-user mode is restricted to loopback connections")
        if not real_ip and not is_loopback(request.url.hostname):
            raise HTTPException(403, "Local single-user mode requires a loopback host")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in settings.origins:
            raise HTTPException(403, "Origin is not allowed")
        identity = Identity(LOCAL_USER_ID)
    else:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 16384 or any(c.isspace() for c in token):
            raise HTTPException(401, "A valid Bearer access token is required", headers={"WWW-Authenticate": "Bearer"})
        try:
            response = await request.app.state.http.get(
                f"{settings.supabase_url}/auth/v1/user",
                headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {token}"},
                timeout=settings.connectivity_timeout_seconds,
            )
            if response.status_code in {401, 403, 400}:
                raise HTTPException(401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
            if response.status_code != 200:
                raise HTTPException(503, "Authentication service is unavailable")
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("id"), str):
                raise ValueError("Invalid authentication response")
            identity = Identity(str(UUID(body["id"])))
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise HTTPException(503, "Authentication service is unavailable") from None
    request.app.state.database.ensure_user(identity.id)
    return identity
