# Ann-Agent

An **A2A-enabled (Agent-to-Agent) microservice agent** built with the
**Microsoft Agent Framework** for Python and the **Microsoft 365 Agent SDK**,
packaged for **Azure Container Apps**.

The service exposes a standard A2A endpoint (`/a2a/v1`) plus an A2A agent card, so
the agent can be discovered and invoked by external orchestrators such as
**Microsoft Copilot Studio**, while its identity, authentication and lifecycle are
managed through **Microsoft Agent 365**.

## Architecture

```
                 ┌──────────────────────────── Azure Container App ────────────────────────────┐
 Copilot Studio  │  FastAPI / ASGI (uvicorn)                                                   │
 or remote  ───► │   ├── GET  /.well-known/agent-card.json   A2A agent card (skills, endpoint) │
 A2A agent       │   ├── POST /a2a/v1                        A2A JSON-RPC (message/send, tasks)│
                 │   ├── GET  /healthz, /readyz              Container App probes              │
                 │   │                                                                         │
                 │   ├── Agent365AuthMiddleware  ── Microsoft 365 Agent SDK JWT validation     │
                 │   └── A2AExecutor ─► Agent (Microsoft Agent Framework) ─► Azure OpenAI      │
                 └─────────────────────────────────────────────────────────────────────────────┘
```

## Project layout

```
.
├── agent/
│   ├── agent.py          # Microsoft Agent Framework agent definition
│   ├── a2a_server.py     # Agent card + A2A JSON-RPC routes
│   ├── agent365.py       # Microsoft 365 Agent SDK: auth, identity, lifecycle
│   ├── settings.py       # Environment driven configuration
│   └── tools.py          # Example tools exposed to the model
├── infra/main.bicep      # Azure Container Apps infrastructure as code
├── tests/test_app.py     # Agent card, A2A invocation and auth tests
├── app.py                # FastAPI application factory
├── main.py               # uvicorn entry point
├── Dockerfile            # Multi-stage, non-root production image
├── deploy.sh             # Azure CLI provisioning + deployment script
├── requirements.txt
├── .env.sample
└── DEPLOYMENT.md
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/.well-known/agent-card.json` | A2A agent card (skills, capabilities, endpoint URL) |
| `GET` | `/.well-known/agent.json` | Alias for pre-1.0 A2A clients |
| `POST` | `/a2a/v1` | A2A JSON-RPC endpoint (`SendMessage`, `SendStreamingMessage`, task methods; A2A v0.3 method names such as `message/send` are accepted by default) |
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/readyz` | Readiness probe + effective configuration |
| `GET` | `/docs` | OpenAPI documentation (A2A routes included) |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.sample .env      # fill in AZURE_OPENAI_ENDPOINT and the deployment name
python main.py           # serves http://localhost:8000
```

Authentication to Azure OpenAI uses `AZURE_OPENAI_API_KEY` when set, otherwise Entra ID
(`az login` locally, managed identity in Azure).

Send an A2A request:

```bash
curl -X POST http://localhost:8000/a2a/v1 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m1","parts":[{"text":"What time is it in Tokyo?"}]}}}'
```

Run the tests (no model calls are made):

```bash
pytest
```

## Configuration

All settings come from environment variables; see [`.env.sample`](.env.sample) for the
complete list.

| Variable | Default | Description |
| --- | --- | --- |
| `AZURE_OPENAI_ENDPOINT` | – | **Required.** Azure OpenAI / Foundry endpoint |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-4o-mini` | Model deployment name |
| `AZURE_OPENAI_API_KEY` | *(empty)* | Optional; empty means Entra ID / managed identity |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public URL advertised in the agent card |
| `A2A_PATH` | `/a2a/v1` | A2A JSON-RPC endpoint path |
| `A2A_STREAMING` | `true` | Stream responses as A2A artifact updates |
| `A2A_V03_COMPAT` | `true` | Also accept A2A v0.3 method names |
| `AGENT365_ENABLED` | `false` | Enable the Microsoft 365 Agent SDK integration |
| `AGENT365_REQUIRE_AUTH` | `false` | Require a valid Entra ID token on `/a2a/v1` |
| `AGENT365_CLIENT_ID` / `AGENT365_TENANT_ID` | – | Entra app registration of the agent |
| `AGENT365_AUTHORIZED_CALLERS` | *(empty)* | Optional allow-list of calling app ids |

## Extending the agent

* **Tools** – add a `@tool` decorated function in `agent/tools.py` and register it in
  `AGENT_TOOLS`; the JSON schema is generated from the type hints and docstring.
* **Skills** – describe new capabilities in `AGENT_SKILLS` (`agent/a2a_server.py`) so
  remote orchestrators can discover them from the agent card.
* **Instructions / model** – override `AGENT_INSTRUCTIONS` and
  `AZURE_OPENAI_DEPLOYMENT_NAME`.

## Deployment

```bash
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com"
./deploy.sh
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full walkthrough, including Entra ID app
registration for Microsoft Agent 365 and how to connect the agent from Microsoft
Copilot Studio.

## Copilot Prompts

- [Build an A2A-enabled agent with Microsoft Agent Framework (Python) and Microsoft Agent 365](.github/prompts/build-a2a-agent365-agent.prompt.md) — a ready-to-use GitHub Copilot prompt for scaffolding an agent built with the Microsoft Agent Framework (Python), deployable to Azure Container Apps, exposed via A2A for use by other agents (e.g. from Copilot Studio), and integrated with the Microsoft Agent 365 SDK for management.
