#!/usr/bin/env bash
#
# Provision Azure resources and deploy the A2A agent to Azure Container Apps.
#
# Prerequisites:
#   * Azure CLI (az) >= 2.60 and logged in (`az login`)
#   * The containerapp extension (installed automatically below)
#   * An existing Azure OpenAI (or Azure AI Foundry) deployment
#
# Usage:
#   ./deploy.sh                       # deploy with defaults / environment overrides
#   RESOURCE_GROUP=my-rg ./deploy.sh  # override any setting via environment variables
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
LOCATION="${LOCATION:-eastus}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-ann-agent}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-cae-ann-agent}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-ca-ann-agent}"
ACR_NAME="${ACR_NAME:-acrannagent$RANDOM}"
IMAGE_NAME="${IMAGE_NAME:-ann-agent}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
LOG_ANALYTICS_NAME="${LOG_ANALYTICS_NAME:-log-ann-agent}"
TARGET_PORT="${TARGET_PORT:-8000}"
MIN_REPLICAS="${MIN_REPLICAS:-1}"
MAX_REPLICAS="${MAX_REPLICAS:-5}"
CPU="${CPU:-1.0}"
MEMORY="${MEMORY:-2.0Gi}"

# Agent configuration
AGENT_NAME="${AGENT_NAME:-Ann Agent}"
AGENT_VERSION="${AGENT_VERSION:-1.0.0}"
A2A_PATH="${A2A_PATH:-/a2a/v1}"
A2A_STREAMING="${A2A_STREAMING:-true}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Model configuration (AZURE_OPENAI_ENDPOINT is required)
AZURE_OPENAI_ENDPOINT="${AZURE_OPENAI_ENDPOINT:-}"
AZURE_OPENAI_DEPLOYMENT_NAME="${AZURE_OPENAI_DEPLOYMENT_NAME:-gpt-4o-mini}"
AZURE_OPENAI_API_VERSION="${AZURE_OPENAI_API_VERSION:-2024-10-21}"
AZURE_OPENAI_API_KEY="${AZURE_OPENAI_API_KEY:-}"

# Microsoft 365 Agent SDK / Agent 365 configuration
AGENT365_ENABLED="${AGENT365_ENABLED:-false}"
AGENT365_REQUIRE_AUTH="${AGENT365_REQUIRE_AUTH:-false}"
AGENT365_CLIENT_ID="${AGENT365_CLIENT_ID:-}"
AGENT365_TENANT_ID="${AGENT365_TENANT_ID:-}"
AGENT365_CLIENT_SECRET="${AGENT365_CLIENT_SECRET:-}"
AGENT365_AUTHORIZED_CALLERS="${AGENT365_AUTHORIZED_CALLERS:-}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
command -v az >/dev/null 2>&1 || fail "Azure CLI (az) is not installed. See https://aka.ms/azure-cli"
az account show >/dev/null 2>&1 || fail "Not logged in to Azure. Run 'az login' first."
[[ -n "$AZURE_OPENAI_ENDPOINT" ]] || fail "AZURE_OPENAI_ENDPOINT must be set (e.g. https://my-aoai.openai.azure.com)."

log "Ensuring the Azure CLI 'containerapp' extension is installed"
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
for provider in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights; do
  if [[ "$(az provider show --namespace "$provider" --query registrationState -o tsv)" != "Registered" ]]; then
    az provider register --namespace "$provider" --only-show-errors >/dev/null
  fi
done

# ---------------------------------------------------------------------------
# Resource group
# ---------------------------------------------------------------------------
if az group show --name "$RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1; then
  log "Reusing existing resource group '$RESOURCE_GROUP'"
else
  log "Creating resource group '$RESOURCE_GROUP' in '$LOCATION'"
  az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --only-show-errors >/dev/null
fi

# ---------------------------------------------------------------------------
# Azure Container Registry + image build
# ---------------------------------------------------------------------------
if az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1; then
  log "Reusing existing container registry '$ACR_NAME'"
else
  log "Creating container registry '$ACR_NAME'"
  az acr create \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Basic \
    --only-show-errors >/dev/null
fi

ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)"
IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

log "Building container image '$IMAGE' with ACR build tasks"
az acr build \
  --registry "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  --file Dockerfile \
  . \
  --only-show-errors

# ---------------------------------------------------------------------------
# Log Analytics workspace + Container Apps environment
# ---------------------------------------------------------------------------
if az monitor log-analytics workspace show \
     --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_NAME" --only-show-errors >/dev/null 2>&1; then
  log "Reusing existing Log Analytics workspace '$LOG_ANALYTICS_NAME'"
else
  log "Creating Log Analytics workspace '$LOG_ANALYTICS_NAME'"
  az monitor log-analytics workspace create \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_NAME" \
    --location "$LOCATION" \
    --only-show-errors >/dev/null
fi

LOG_CUSTOMER_ID="$(az monitor log-analytics workspace show \
  --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_NAME" --query customerId -o tsv)"
LOG_SHARED_KEY="$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_NAME" --query primarySharedKey -o tsv)"

if az containerapp env show --name "$ENVIRONMENT_NAME" --resource-group "$RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1; then
  log "Reusing existing Container Apps environment '$ENVIRONMENT_NAME'"
else
  log "Creating Container Apps environment '$ENVIRONMENT_NAME'"
  az containerapp env create \
    --name "$ENVIRONMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --logs-workspace-id "$LOG_CUSTOMER_ID" \
    --logs-workspace-key "$LOG_SHARED_KEY" \
    --only-show-errors >/dev/null
fi

# ---------------------------------------------------------------------------
# Container app
# ---------------------------------------------------------------------------
# Secrets are stored as Container App secrets and referenced by environment
# variables, never baked into the image.
secret_args=()
env_vars=(
  "AGENT_NAME=$AGENT_NAME"
  "AGENT_VERSION=$AGENT_VERSION"
  "LOG_LEVEL=$LOG_LEVEL"
  "PORT=$TARGET_PORT"
  "A2A_PATH=$A2A_PATH"
  "A2A_STREAMING=$A2A_STREAMING"
  "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT"
  "AZURE_OPENAI_DEPLOYMENT_NAME=$AZURE_OPENAI_DEPLOYMENT_NAME"
  "AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION"
  "AGENT365_ENABLED=$AGENT365_ENABLED"
  "AGENT365_REQUIRE_AUTH=$AGENT365_REQUIRE_AUTH"
  "AGENT365_CLIENT_ID=$AGENT365_CLIENT_ID"
  "AGENT365_TENANT_ID=$AGENT365_TENANT_ID"
  "AGENT365_AUTHORIZED_CALLERS=$AGENT365_AUTHORIZED_CALLERS"
)

if [[ -n "$AZURE_OPENAI_API_KEY" ]]; then
  secret_args+=("azure-openai-api-key=$AZURE_OPENAI_API_KEY")
  env_vars+=("AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key")
fi

if [[ -n "$AGENT365_CLIENT_SECRET" ]]; then
  secret_args+=("agent365-client-secret=$AGENT365_CLIENT_SECRET")
  env_vars+=("AGENT365_CLIENT_SECRET=secretref:agent365-client-secret")
fi

if az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1; then
  log "Updating existing container app '$CONTAINER_APP_NAME'"
  if [[ ${#secret_args[@]} -gt 0 ]]; then
    az containerapp secret set \
      --name "$CONTAINER_APP_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --secrets "${secret_args[@]}" \
      --only-show-errors >/dev/null
  fi
  az containerapp update \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$IMAGE" \
    --min-replicas "$MIN_REPLICAS" \
    --max-replicas "$MAX_REPLICAS" \
    --cpu "$CPU" \
    --memory "$MEMORY" \
    --set-env-vars "${env_vars[@]}" \
    --only-show-errors >/dev/null
else
  log "Creating container app '$CONTAINER_APP_NAME'"
  create_args=(
    --name "$CONTAINER_APP_NAME"
    --resource-group "$RESOURCE_GROUP"
    --environment "$ENVIRONMENT_NAME"
    --image "$IMAGE"
    --registry-server "$ACR_LOGIN_SERVER"
    --system-assigned
    --ingress external
    --target-port "$TARGET_PORT"
    --transport auto
    --min-replicas "$MIN_REPLICAS"
    --max-replicas "$MAX_REPLICAS"
    --cpu "$CPU"
    --memory "$MEMORY"
    --env-vars "${env_vars[@]}"
    --only-show-errors
  )
  if [[ ${#secret_args[@]} -gt 0 ]]; then
    create_args+=(--secrets "${secret_args[@]}")
  fi
  az containerapp create "${create_args[@]}" >/dev/null
fi

# ---------------------------------------------------------------------------
# Managed identity: pull from ACR and (optionally) call Azure OpenAI
# ---------------------------------------------------------------------------
PRINCIPAL_ID="$(az containerapp show \
  --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query identity.principalId -o tsv)"
ACR_ID="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"

log "Granting the container app's managed identity AcrPull on '$ACR_NAME'"
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$ACR_ID" \
  --only-show-errors >/dev/null 2>&1 || log "AcrPull role assignment already exists (skipped)"

log "Configuring managed identity based registry authentication"
az containerapp registry set \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --server "$ACR_LOGIN_SERVER" \
  --identity system \
  --only-show-errors >/dev/null

# ---------------------------------------------------------------------------
# Publish the public URL back into the app so the agent card is correct
# ---------------------------------------------------------------------------
FQDN="$(az containerapp show \
  --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"
PUBLIC_BASE_URL="https://${FQDN}"

log "Setting PUBLIC_BASE_URL to $PUBLIC_BASE_URL"
az containerapp update \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --set-env-vars "PUBLIC_BASE_URL=$PUBLIC_BASE_URL" \
  --only-show-errors >/dev/null

cat <<EOF

Deployment complete.

  Resource group : $RESOURCE_GROUP
  Container app  : $CONTAINER_APP_NAME
  Image          : $IMAGE
  Agent card     : ${PUBLIC_BASE_URL}/.well-known/agent-card.json
  A2A endpoint   : ${PUBLIC_BASE_URL}${A2A_PATH}
  Health probe   : ${PUBLIC_BASE_URL}/healthz

If the agent authenticates to Azure OpenAI with its managed identity, grant it the
'Cognitive Services OpenAI User' role on the Azure OpenAI resource:

  az role assignment create \\
    --assignee-object-id $PRINCIPAL_ID \\
    --assignee-principal-type ServicePrincipal \\
    --role "Cognitive Services OpenAI User" \\
    --scope <azure-openai-resource-id>

Stream logs with:

  az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow

EOF
