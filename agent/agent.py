# Copyright (c) Microsoft. All rights reserved.
"""Microsoft Agent Framework agent definition."""

from __future__ import annotations

import logging
from functools import lru_cache

from agent_framework import Agent
from agent_framework_openai import OpenAIChatClient

from .settings import Settings, get_settings
from .tools import AGENT_TOOLS

logger = logging.getLogger(__name__)


def create_chat_client(settings: Settings | None = None) -> OpenAIChatClient:
    """Create the Azure OpenAI backed chat client used by the agent.

    Uses an API key when ``AZURE_OPENAI_API_KEY`` is configured, otherwise falls
    back to Entra ID (managed identity in Azure Container Apps, developer
    credentials locally).
    """
    settings = settings or get_settings()
    azure = settings.azure_openai
    azure.validate()

    if azure.use_managed_identity:
        # Imported lazily so that unit tests and the agent card endpoint do not
        # require the azure-identity dependency chain to be initialized.
        from azure.identity.aio import DefaultAzureCredential

        logger.info("Connecting to Azure OpenAI at %s using Entra ID credentials.", azure.endpoint)
        return OpenAIChatClient(
            model=azure.deployment_name,
            azure_endpoint=azure.endpoint,
            api_version=azure.api_version,
            credential=DefaultAzureCredential(),
        )

    logger.info("Connecting to Azure OpenAI at %s using an API key.", azure.endpoint)
    return OpenAIChatClient(
        model=azure.deployment_name,
        azure_endpoint=azure.endpoint,
        api_version=azure.api_version,
        api_key=azure.api_key,
    )


def create_agent(settings: Settings | None = None) -> Agent:
    """Build the Microsoft Agent Framework agent with its instructions and tools."""
    settings = settings or get_settings()
    return create_chat_client(settings).as_agent(
        name=settings.agent_name,
        description=settings.agent_description,
        instructions=settings.agent_instructions,
        tools=AGENT_TOOLS,
    )


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    """Return the process-wide agent singleton."""
    return create_agent()
