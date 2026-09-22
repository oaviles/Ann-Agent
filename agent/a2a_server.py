# Copyright (c) Microsoft. All rights reserved.
"""A2A (Agent-to-Agent) protocol hosting for the Microsoft Agent Framework agent.

The agent is exposed through:

* ``/.well-known/agent-card.json`` - the A2A Agent Card describing skills,
  capabilities and the endpoint URL (an ``/.well-known/agent.json`` alias is
  registered by the application for older clients).
* ``/a2a/v1`` - the A2A JSON-RPC endpoint used to send messages/tasks and to
  receive (optionally streamed) responses.
"""

from __future__ import annotations

from dataclasses import dataclass

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from agent_framework import Agent
from agent_framework_a2a import A2AExecutor
from starlette.routing import BaseRoute

from .settings import Settings, get_settings

AGENT_CARD_PATH = "/.well-known/agent-card.json"
LEGACY_AGENT_CARD_PATH = "/.well-known/agent.json"

#: Skills advertised to callers (for example a Copilot Studio orchestrator).
AGENT_SKILLS = [
    AgentSkill(
        id="general_assistance",
        name="General assistance",
        description="Answer questions and complete short tasks in natural language.",
        tags=["chat", "assistant", "qna"],
        examples=["Summarize the key risks of moving our billing service to Azure Container Apps."],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    ),
    AgentSkill(
        id="date_and_time",
        name="Date and time calculations",
        description="Report the current time in a given time zone and count business days between dates.",
        tags=["time", "calendar", "tools"],
        examples=["What time is it in Tokyo?", "How many business days are between 2026-01-05 and 2026-01-30?"],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    ),
]


def build_agent_card(settings: Settings | None = None) -> AgentCard:
    """Build the A2A Agent Card advertised by this service."""
    settings = settings or get_settings()
    return AgentCard(
        name=settings.agent_name,
        description=settings.agent_description,
        version=settings.agent_version,
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=settings.a2a_streaming, push_notifications=False),
        supported_interfaces=[AgentInterface(url=settings.a2a_url, protocol_binding="JSONRPC")],
        skills=AGENT_SKILLS,
    )


def build_legacy_agent_card(settings: Settings | None = None) -> dict[str, object]:
    """Build the pre-1.0 Agent Card shape used by older A2A clients."""
    settings = settings or get_settings()
    card = agent_card_to_dict(build_agent_card(settings))
    card["url"] = settings.a2a_url
    card["preferredTransport"] = "JSONRPC"
    card.pop("supportedInterfaces", None)
    return card


@dataclass
class A2AHost:
    """Container for the A2A routes and the agent they expose."""

    agent: Agent
    agent_card: AgentCard
    agent_card_routes: list[BaseRoute]
    jsonrpc_routes: list[BaseRoute]


def build_a2a_host(agent: Agent, settings: Settings | None = None) -> A2AHost:
    """Create the A2A request handler and Starlette routes for ``agent``."""
    settings = settings or get_settings()
    agent_card = build_agent_card(settings)
    request_handler = DefaultRequestHandler(
        agent_executor=A2AExecutor(agent, stream=settings.a2a_streaming),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    return A2AHost(
        agent=agent,
        agent_card=agent_card,
        agent_card_routes=list(create_agent_card_routes(agent_card, card_url=AGENT_CARD_PATH)),
        jsonrpc_routes=list(
            create_jsonrpc_routes(
                request_handler,
                rpc_url=settings.a2a_path,
                enable_v0_3_compat=settings.a2a_v03_compat,
            )
        ),
    )
