---
mode: agent
description: Build a Python Microsoft Agent Framework agent, deployable to Azure Container Apps, exposed via A2A for Copilot Studio, and managed with Microsoft Agent 365.
---

# Prompt: Build an A2A-enabled Agent with Microsoft Agent Framework (Python) and Microsoft Agent 365

Use this prompt with GitHub Copilot (Chat or Coding Agent) to scaffold and implement the agent described below.

## Goal

Create an agent-based application using the **Microsoft Agent Framework** for **Python** that:

1. Implements an agent capable of handling requests and producing responses (a standard conversational/task agent).
2. Is packaged and deployable to an **Azure Container App**.
3. Exposes an **A2A (Agent-to-Agent)** protocol endpoint so that the agent can be invoked by other agents, specifically an agent orchestrated from **Microsoft Copilot Studio**.
4. Integrates the **Microsoft Agent 365 SDK** so the agent can be registered, governed, and managed through **Microsoft Agent 365**.

## Detailed Requirements

### 1. Agent implementation (Microsoft Agent Framework, Python)

- Use the Microsoft Agent Framework Python SDK (`agent-framework` package) to define the agent, its instructions, tools/functions, and model configuration.
- Structure the project with a clear entry point (e.g., `main.py` or `app.py`) and a dedicated module for the agent definition (e.g., `agent/agent.py`).
- Include configuration for the model/connection (e.g., Azure OpenAI or Azure AI Foundry) via environment variables, with a `.env.sample` file documenting required settings (endpoint, deployment/model name, credentials, API version).
- Add at least one example tool/function the agent can call, to demonstrate extensibility.
- Include a `requirements.txt` (or `pyproject.toml`) pinning the Agent Framework and any other dependencies.

### 2. A2A protocol support

- Expose the agent over the **A2A protocol** (Agent2Agent) so external agents/orchestrators can discover and call it.
- Implement:
  - An **Agent Card** endpoint (`/.well-known/agent.json` or equivalent) describing the agent's capabilities, skills, and endpoint URL, per the A2A specification.
  - The A2A task/message endpoints required for another agent to send a task and receive a response (synchronous and, if feasible, streaming).
- Use the official/community A2A Python SDK (e.g., `a2a-sdk`) or the Agent Framework's built-in A2A hosting support if available, wrapping the agent defined in step 1.
- Document how an external caller (e.g., an agent built in **Microsoft Copilot Studio** using its "Agent" or "connector" capability) would register this agent's A2A endpoint URL and Agent Card.

### 3. Azure Container Apps deployment

- Provide a `Dockerfile` that builds a minimal, production-ready container image for the Python app (multi-stage build, non-root user, exposes the HTTP port used by the A2A server, e.g., 8000).
- Provide deployment assets to run the container in **Azure Container Apps**:
  - Infrastructure-as-code (Bicep or `azd`-compatible `infra/` templates) defining the Container App, Container Apps Environment, Log Analytics workspace, and (if needed) Azure Container Registry.
  - Ingress configuration allowing external HTTPS access to the A2A endpoints.
  - Environment variable / secret wiring so the container receives model endpoint/credentials from Container App secrets (not hardcoded).
- Document the deployment steps (e.g., `az containerapp up` or `azd up`) in a `DEPLOYMENT.md`.

### 4. Microsoft Agent 365 SDK integration

- Add the **Microsoft Agent 365 SDK** to the project dependencies and initialize it alongside the agent so that:
  - The agent registers its identity, capabilities, and lifecycle with **Microsoft Agent 365** for centralized management, observability, and governance.
  - Agent 365 policies (e.g., access control, auditing) can be applied to this agent once registered.
- Document any additional Azure AD / Entra app registration steps required to onboard the agent into Microsoft Agent 365 (e.g., app registration, permissions, tenant configuration).
- Clearly separate this integration (e.g., `agent/agent365.py`) from the core agent logic so it can be toggled via configuration for local development.

## Suggested Project Layout

```
.
├── agent/
│   ├── agent.py          # Microsoft Agent Framework agent definition
│   ├── a2a_server.py     # A2A protocol server exposing the agent
│   └── agent365.py       # Microsoft Agent 365 SDK registration/management
├── infra/                # Bicep/azd templates for Azure Container Apps
├── Dockerfile
├── requirements.txt
├── .env.sample
├── DEPLOYMENT.md
└── main.py
```

## Acceptance Criteria

- [ ] Agent runs locally and responds to a basic request using the Microsoft Agent Framework.
- [ ] `/.well-known/agent.json` (Agent Card) is served and describes the agent per the A2A spec.
- [ ] The agent can receive and respond to an A2A task invocation from a sample client.
- [ ] Container image builds successfully from the provided `Dockerfile`.
- [ ] Infra templates deploy the container to an Azure Container App with public HTTPS ingress.
- [ ] Microsoft Agent 365 SDK is initialized and the agent can be registered/managed through Microsoft Agent 365.
- [ ] README/DEPLOYMENT docs explain how to configure Copilot Studio to call this agent via A2A.
