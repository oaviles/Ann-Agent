# Copyright (c) Microsoft. All rights reserved.
"""FastAPI/ASGI application exposing the agent over the A2A protocol."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from a2a.server.routes import add_a2a_routes_to_fastapi
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent.a2a_server import AGENT_CARD_PATH, LEGACY_AGENT_CARD_PATH, build_a2a_host, build_legacy_agent_card
from agent.agent import create_agent
from agent.agent365 import Agent365AuthMiddleware, Agent365Integration
from agent.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application hosting the A2A endpoints."""
    settings = settings or get_settings()
    configure_logging(settings)

    agent365 = Agent365Integration(settings)
    a2a_host = build_a2a_host(create_agent(settings), settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await agent365.start()
        logger.info("Agent '%s' listening for A2A requests on %s", settings.agent_name, settings.a2a_url)
        try:
            yield
        finally:
            await agent365.stop()

    app = FastAPI(
        title=settings.agent_name,
        description=settings.agent_description,
        version=settings.agent_version,
        lifespan=lifespan,
    )

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=a2a_host.agent_card_routes,
        jsonrpc_routes=a2a_host.jsonrpc_routes,
    )

    @app.get(LEGACY_AGENT_CARD_PATH, include_in_schema=False)
    async def legacy_agent_card() -> JSONResponse:
        """Serve the agent card at the pre-1.0 A2A well-known path."""
        return JSONResponse(build_legacy_agent_card(settings))

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness probe used by Azure Container Apps."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, Any]:
        """Readiness probe reporting the agent and Agent 365 configuration."""
        return {
            "status": "ready",
            "agent": settings.agent_name,
            "version": settings.agent_version,
            "a2aEndpoint": settings.a2a_url,
            "agentCard": f"{settings.public_base_url.rstrip('/')}{AGENT_CARD_PATH}",
            "agent365Enabled": agent365.enabled,
            "authRequired": agent365.auth_required,
        }

    # Protect the A2A endpoints with Microsoft 365 Agent SDK token validation.
    app.add_middleware(
        Agent365AuthMiddleware,
        integration=agent365,
        protected_paths=[settings.a2a_path],
    )

    app.state.settings = settings
    app.state.agent = a2a_host.agent
    app.state.agent365 = agent365
    return app


app = create_app()
