# Deployment guide

This guide covers building the container image, deploying it to **Azure Container
Apps**, onboarding the agent into **Microsoft Agent 365**, and registering the A2A
endpoint with **Microsoft Copilot Studio**.

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| Azure subscription | Contributor + User Access Administrator (for role assignments) |
| [Azure CLI](https://aka.ms/azure-cli) 2.60+ | `az login` before deploying |
| Azure OpenAI / Azure AI Foundry deployment | Endpoint + deployment (model) name |
| Docker (optional) | Only needed for local image builds; `deploy.sh` uses ACR build tasks |
| Entra ID app registration | Required for Agent 365 and authenticated A2A calls |

## 2. One-command deployment

```bash
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4o-mini"

./deploy.sh
```

`deploy.sh` is idempotent and performs the following steps:

1. Registers the `Microsoft.App` / `Microsoft.OperationalInsights` providers and installs the `containerapp` CLI extension.
2. Creates the resource group, Azure Container Registry, and Log Analytics workspace.
3. Builds the image remotely with `az acr build` (no local Docker required).
4. Creates the Container Apps environment and the container app with **external HTTPS ingress** on port `8000`.
5. Assigns the app's **system-assigned managed identity** the `AcrPull` role and switches the registry to identity-based authentication.
6. Sets `PUBLIC_BASE_URL` to the app's FQDN so the published agent card advertises the correct A2A URL.

Every setting can be overridden with environment variables, for example:

```bash
RESOURCE_GROUP=rg-agents LOCATION=westeurope CONTAINER_APP_NAME=ca-ann \
AGENT365_ENABLED=true AGENT365_REQUIRE_AUTH=true \
AGENT365_CLIENT_ID=<app-id> AGENT365_TENANT_ID=<tenant-id> \
./deploy.sh
```

Secrets (`AZURE_OPENAI_API_KEY`, `AGENT365_CLIENT_SECRET`) are stored as **Container
App secrets** and referenced through `secretref:` environment variables – they are
never baked into the image.

### Model authentication with managed identity

Leave `AZURE_OPENAI_API_KEY` empty to authenticate with the container app's managed
identity (recommended). Grant the identity access to the Azure OpenAI resource:

```bash
az role assignment create \
  --assignee-object-id "$(az containerapp show -n ca-ann-agent -g rg-ann-agent --query identity.principalId -o tsv)" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope "$(az cognitiveservices account show -n <aoai-name> -g <aoai-rg> --query id -o tsv)"
```

## 3. Infrastructure as code (optional)

`infra/main.bicep` provisions the same topology (Log Analytics workspace, Container
Apps environment, container app with liveness/readiness probes and managed identity):

```bash
az deployment group create \
  --resource-group rg-ann-agent \
  --template-file infra/main.bicep \
  --parameters containerImage=<acr>.azurecr.io/ann-agent:1.0.0 \
               registryServer=<acr>.azurecr.io \
               azureOpenAiEndpoint=https://<your-resource>.openai.azure.com
```

## 4. Verifying the deployment

```bash
BASE_URL="https://$(az containerapp show -n ca-ann-agent -g rg-ann-agent --query properties.configuration.ingress.fqdn -o tsv)"

curl "$BASE_URL/healthz"
curl "$BASE_URL/.well-known/agent-card.json"

# A2A message (v0.3 compatible method names are accepted by default)
curl -X POST "$BASE_URL/a2a/v1" \
  -H "Content-Type: application/json" \
  -d '{
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {"message": {"role": "user", "messageId": "m1", "parts": [{"text": "What time is it in Tokyo?"}]}}
      }'
```

For A2A 1.0 method names, send the `A2A-Version: 1.0` header and use `SendMessage` /
`SendStreamingMessage`.

Stream logs:

```bash
az containerapp logs show -n ca-ann-agent -g rg-ann-agent --follow
```

## 5. Entra ID app registration (Microsoft Agent 365)

1. **Create the app registration** that represents the agent:

   ```bash
   az ad app create --display-name "Ann Agent" --sign-in-audience AzureADMyOrg
   ```

2. **Expose an API / set the identifier URI** so inbound tokens can target the agent.
   The token audience must equal the app's **client id** (`AGENT365_CLIENT_ID`).

3. **Create a service principal** so the app can be governed in the tenant:

   ```bash
   az ad sp create --id <app-id>
   ```

4. **Choose a credential**:
   * Preferred: the container app's managed identity (`AGENT365_CLIENT_SECRET` empty,
     `AuthTypes.system_managed_identity` is used automatically).
   * Alternative: a client secret stored as a Container App secret.

5. **Grant admin consent** for any Microsoft Graph permissions your scenario needs
   (for example `User.Read.All` for people lookups). Agent 365 policies – access
   control, auditing, data boundaries – are then applied to this identity.

6. **Enable the integration** on the container app:

   ```bash
   az containerapp update -n ca-ann-agent -g rg-ann-agent --set-env-vars \
     AGENT365_ENABLED=true AGENT365_REQUIRE_AUTH=true \
     AGENT365_CLIENT_ID=<app-id> AGENT365_TENANT_ID=<tenant-id>
   ```

7. **Register the agent in Microsoft Agent 365** using the manifest published on
   startup (visible in the container logs and at `/readyz`): agent name, version,
   A2A endpoint, agent card URL, and authentication mode.

Optionally restrict which applications may call the agent:

```bash
az containerapp update -n ca-ann-agent -g rg-ann-agent \
  --set-env-vars AGENT365_AUTHORIZED_CALLERS=<copilot-studio-app-id>
```

Requests without a valid bearer token (audience = `AGENT365_CLIENT_ID`, issuer bound
to `AGENT365_TENANT_ID`) receive `401 Unauthorized` when `AGENT365_REQUIRE_AUTH=true`.
The agent card and health endpoints stay anonymous so the agent remains discoverable.

## 6. Connecting from Microsoft Copilot Studio

1. In Copilot Studio open your agent and go to **Agents → Add an agent → Connect to an
   existing agent (A2A)**.
2. Provide the **Agent card URL**:
   `https://<your-app>.<region>.azurecontainerapps.io/.well-known/agent-card.json`
   Copilot Studio reads the card and discovers the A2A endpoint
   (`https://<your-app>.../a2a/v1`), the skills, and the streaming capability.
3. Configure authentication:
   * *No authentication* – for development only (`AGENT365_REQUIRE_AUTH=false`).
   * *Microsoft Entra ID* – supply the agent's **client id** as the resource/scope
     (`api://<agent-client-id>/.default`). Add the Copilot Studio application id to
     `AGENT365_AUTHORIZED_CALLERS` to restrict callers.
4. Save and test: the orchestrator sends A2A `message/send` requests and renders the
   agent's response, including streamed artifact updates when `A2A_STREAMING=true`.

## 7. Operations

| Task | Command |
| --- | --- |
| Roll out a new image | `IMAGE_TAG=$(date -u +%Y%m%d%H%M%S) ./deploy.sh` |
| Scale | `az containerapp update -n ca-ann-agent -g rg-ann-agent --min-replicas 2 --max-replicas 10` |
| Inspect revisions | `az containerapp revision list -n ca-ann-agent -g rg-ann-agent -o table` |
| Rotate a secret | `az containerapp secret set -n ca-ann-agent -g rg-ann-agent --secrets azure-openai-api-key=<new>` |

> **Note:** A2A tasks are kept in an in-memory task store. Run a single replica, or
> replace `InMemoryTaskStore` in `agent/a2a_server.py` with a shared store when you
> need multi-replica task continuity.
