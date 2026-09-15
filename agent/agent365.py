# Copyright (c) Microsoft. All rights reserved.
"""Microsoft 365 Agent SDK (Agent 365) integration.

This module is intentionally separated from the core agent logic so that it can
be toggled off for local development (``AGENT365_ENABLED=false``).

It provides:

* **Identity & lifecycle** - the agent manifest (identity, capabilities,
  endpoints) that is published on startup so the agent can be registered,
  governed and observed through Microsoft Agent 365.
* **Authentication** - validation of inbound Entra ID bearer tokens using the
  Microsoft 365 Agent SDK ``JwtTokenValidator``, plus an ASGI middleware that
  protects the A2A endpoint routes.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from microsoft_agents.hosting.core import (
    AgentAuthConfiguration,
    AuthTypes,
    ClaimsIdentity,
    JwtTokenValidator,
)
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: Request scope key holding the validated :class:`ClaimsIdentity`.
CLAIMS_IDENTITY_KEY = "agent365_claims_identity"

_APP_ID_CLAIMS = ("appid", "azp")


class Agent365Error(Exception):
    """Raised when the Agent 365 integration is misconfigured."""


class Agent365Integration:
    """Lifecycle, identity and authentication helper backed by the M365 Agent SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._config: AgentAuthConfiguration | None = None
        self._validator: JwtTokenValidator | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def enabled(self) -> bool:
        return self._settings.agent365.enabled

    @property
    def auth_required(self) -> bool:
        """True when inbound requests must present a valid Entra ID token."""
        return self.enabled and self._settings.agent365.require_auth

    @property
    def auth_configuration(self) -> AgentAuthConfiguration:
        """Return (and lazily build) the M365 Agent SDK authentication configuration."""
        if self._config is None:
            agent365 = self._settings.agent365
            if not agent365.client_id or not agent365.tenant_id:
                raise Agent365Error(
                    "AGENT365_CLIENT_ID and AGENT365_TENANT_ID must be set when AGENT365_ENABLED is true."
                )
            auth_type = AuthTypes.client_secret if agent365.client_secret else AuthTypes.system_managed_identity
            self._config = AgentAuthConfiguration(
                auth_type=auth_type,
                client_id=agent365.client_id,
                tenant_id=agent365.tenant_id,
                client_secret=agent365.client_secret or None,
                issuers=agent365.issuers or None,
                validate_issuer=agent365.validate_issuer,
            )
        return self._config

    @property
    def token_validator(self) -> JwtTokenValidator:
        """Return (and lazily build) the M365 Agent SDK JWT validator."""
        if self._validator is None:
            self._validator = JwtTokenValidator(self.auth_configuration)
        return self._validator

    async def authenticate(self, authorization_header: str | None) -> ClaimsIdentity:
        """Validate an inbound ``Authorization`` header value.

        Raises:
            PermissionError: when the header is missing, malformed, the token is
                invalid, or the caller is not in the configured allow-list.
        """
        if not authorization_header:
            raise PermissionError("Missing Authorization header.")

        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise PermissionError("Authorization header must use the bearer scheme.")

        try:
            identity = await self.token_validator.validate_token(token.strip())
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as 401
            logger.warning("Rejected inbound token: %s", exc)
            raise PermissionError("Invalid bearer token.") from exc

        self._authorize_caller(identity)
        return identity

    def _authorize_caller(self, identity: ClaimsIdentity) -> None:
        allowed = {caller.lower() for caller in self._settings.agent365.authorized_callers}
        if not allowed:
            return
        caller_ids = {
            str(identity.claims.get(claim)).lower() for claim in _APP_ID_CLAIMS if identity.claims.get(claim)
        }
        if not caller_ids & allowed:
            logger.warning("Rejected caller application id(s): %s", sorted(caller_ids))
            raise PermissionError("Caller application is not authorized to invoke this agent.")

    def manifest(self) -> dict[str, Any]:
        """Return the agent identity/capability manifest used for Agent 365 registration."""
        settings = self._settings
        return {
            "name": settings.agent_name,
            "description": settings.agent_description,
            "version": settings.agent_version,
            "publisher": {"clientId": settings.agent365.client_id, "tenantId": settings.agent365.tenant_id},
            "endpoints": {
                "a2a": settings.a2a_url,
                "agentCard": f"{settings.public_base_url.rstrip('/')}/.well-known/agent-card.json",
            },
            "capabilities": {
                "protocol": "a2a",
                "streaming": settings.a2a_streaming,
                "authentication": "entra-id" if self.auth_required else "anonymous",
            },
        }

    async def start(self) -> None:
        """Publish the agent identity and capabilities for Agent 365 management."""
        if not self.enabled:
            logger.info("Agent 365 integration disabled (AGENT365_ENABLED=false).")
            return

        # Building the configuration validates the Entra app registration settings
        # and primes the JWT validator used for inbound request authorization.
        self.auth_configuration
        if self.auth_required:
            self.token_validator
        logger.info("Agent 365 integration started for agent manifest: %s", self.manifest())

    async def stop(self) -> None:
        """Release Agent 365 resources on shutdown."""
        if not self.enabled:
            return
        self._validator = None
        self._config = None
        logger.info("Agent 365 integration stopped.")


class Agent365AuthMiddleware:
    """ASGI middleware validating Entra ID tokens on the protected paths."""

    def __init__(self, app: ASGIApp, integration: Agent365Integration, protected_paths: Sequence[str]) -> None:
        self.app = app
        self.integration = integration
        self.protected_paths = tuple(protected_paths)

    def _is_protected(self, path: str) -> bool:
        return any(path == prefix or path.startswith(f"{prefix.rstrip('/')}/") for prefix in self.protected_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.integration.auth_required or not self._is_protected(scope["path"]):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        try:
            identity = await self.integration.authenticate(request.headers.get("authorization"))
        except PermissionError as exc:
            response = JSONResponse(
                {"error": "unauthorized", "message": str(exc)},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        scope[CLAIMS_IDENTITY_KEY] = identity
        await self.app(scope, receive, send)


def get_claims_identity(request: Request) -> ClaimsIdentity | None:
    """Return the validated claims identity for the current request, if any."""
    return request.scope.get(CLAIMS_IDENTITY_KEY)


AuthenticateCallable = Callable[[str | None], Awaitable[ClaimsIdentity]]
