# Copyright (c) Microsoft. All rights reserved.
"""Tests for the A2A agent service.

The tests use a stub agent so they never call a real model endpoint.
"""

from __future__ import annotations

import os
import dataclasses
from collections.abc import Sequence
from typing import Any

import pytest

os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-key")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")
os.environ.setdefault("PUBLIC_BASE_URL", "https://agent.example.com")

from a2a.server.request_handlers.response_helpers import agent_card_to_dict  # noqa: E402
from a2a.server.routes import add_a2a_routes_to_fastapi  # noqa: E402
from agent_framework import AgentResponse, Message  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agent.a2a_server import build_a2a_host, build_agent_card  # noqa: E402
from agent.agent365 import Agent365AuthMiddleware, Agent365Integration  # noqa: E402
from agent.settings import Settings  # noqa: E402
from agent.tools import count_business_days, get_current_time  # noqa: E402


class _StubSession:
    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id


class _StubAgent:
    """Minimal agent compatible with the A2A executor contract."""

    name = "Stub Agent"

    def create_session(self, session_id: str | None = None, **_: Any) -> _StubSession:
        return _StubSession(session_id)

    async def run(self, query: Any, *, session: Any = None, stream: bool = False, **_: Any) -> AgentResponse:
        return AgentResponse(messages=[Message(role="assistant", contents=[f"echo: {query}"])])


def _build_test_app(settings: Settings, protected_paths: Sequence[str] | None = None) -> FastAPI:
    host = build_a2a_host(_StubAgent(), settings)  # type: ignore[arg-type]
    app = FastAPI()
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=host.agent_card_routes,
        jsonrpc_routes=host.jsonrpc_routes,
    )
    if protected_paths:
        app.add_middleware(
            Agent365AuthMiddleware,
            integration=Agent365Integration(settings),
            protected_paths=protected_paths,
        )
    return app


@pytest.fixture
def settings() -> Settings:
    return Settings()


def test_agent_card_advertises_a2a_endpoint(settings: Settings) -> None:
    card = agent_card_to_dict(build_agent_card(settings))

    assert card["name"] == settings.agent_name
    assert card["version"] == settings.agent_version
    assert card["supportedInterfaces"][0]["url"] == "https://agent.example.com/a2a/v1"
    assert {skill["id"] for skill in card["skills"]} == {"general_assistance", "date_and_time"}


def test_agent_card_is_served_on_well_known_path(settings: Settings) -> None:
    with TestClient(_build_test_app(settings)) as client:
        response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert response.json()["name"] == settings.agent_name


def test_a2a_message_send_returns_agent_response(settings: Settings) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": "msg-1",
                "parts": [{"text": "hello"}],
            }
        },
    }

    non_streaming = dataclasses.replace(settings, a2a_streaming=False)
    with TestClient(_build_test_app(non_streaming)) as client:
        response = client.post(non_streaming.a2a_path, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "error" not in body, body
    assert "echo: hello" in response.text


def test_protected_a2a_endpoint_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT365_ENABLED", "true")
    monkeypatch.setenv("AGENT365_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AGENT365_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("AGENT365_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    secured = Settings()

    with TestClient(_build_test_app(secured, protected_paths=[secured.a2a_path])) as client:
        unauthorized = client.post(secured.a2a_path, json={"jsonrpc": "2.0", "id": "1", "method": "message/send"})
        allowed = client.get("/.well-known/agent-card.json")

    assert unauthorized.status_code == 401
    assert unauthorized.headers["WWW-Authenticate"] == "Bearer"
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_authenticate_rejects_non_bearer_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT365_ENABLED", "true")
    monkeypatch.setenv("AGENT365_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AGENT365_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("AGENT365_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    integration = Agent365Integration(Settings())

    with pytest.raises(PermissionError):
        await integration.authenticate("Basic dXNlcjpwYXNz")


def test_tools_are_invocable() -> None:
    assert count_business_days.func("2026-01-05", "2026-01-09") == 5
    assert get_current_time.func("UTC").endswith("+00:00")

    with pytest.raises(ValueError):
        count_business_days.func("2026-01-09", "2026-01-05")
