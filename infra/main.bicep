// Azure Container Apps infrastructure for the A2A agent.
// Deploy with:
//   az deployment group create -g <rg> -f infra/main.bicep -p containerImage=<acr>/ann-agent:<tag> ...
targetScope = 'resourceGroup'

@description('Base name used to derive resource names.')
param nameSuffix string = 'ann-agent'

@description('Location for all resources.')
param location string = resourceGroup().location

@description('Fully qualified container image, e.g. myacr.azurecr.io/ann-agent:1.0.0.')
param containerImage string

@description('Login server of the Azure Container Registry hosting the image.')
param registryServer string

@description('Azure OpenAI endpoint used by the agent.')
param azureOpenAiEndpoint string

@description('Azure OpenAI deployment (model) name.')
param azureOpenAiDeploymentName string = 'gpt-4o-mini'

@description('Azure OpenAI API version.')
param azureOpenAiApiVersion string = '2024-10-21'

@description('Azure OpenAI API key. Leave empty to authenticate with the managed identity.')
@secure()
param azureOpenAiApiKey string = ''

@description('Enable the Microsoft 365 Agent SDK (Agent 365) integration.')
param agent365Enabled bool = false

@description('Require a valid Entra ID token on the A2A endpoint.')
param agent365RequireAuth bool = false

@description('Entra application (client) id of the agent app registration.')
param agent365ClientId string = ''

@description('Entra tenant id of the agent app registration.')
param agent365TenantId string = ''

@description('Container port exposed by the agent.')
param targetPort int = 8000

@description('Minimum number of replicas.')
param minReplicas int = 1

@description('Maximum number of replicas.')
param maxReplicas int = 5

var logAnalyticsName = 'log-${nameSuffix}'
var environmentName = 'cae-${nameSuffix}'
var containerAppName = 'ca-${nameSuffix}'
var useApiKey = !empty(azureOpenAiApiKey)

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: 'system'
        }
      ]
      secrets: useApiKey ? [
        {
          name: 'azure-openai-api-key'
          value: azureOpenAiApiKey
        }
      ] : []
    }
    template: {
      containers: [
        {
          name: 'agent'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          env: concat([
            {
              name: 'PORT'
              value: string(targetPort)
            }
            {
              name: 'PUBLIC_BASE_URL'
              value: 'https://${containerAppName}.${managedEnvironment.properties.defaultDomain}'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
              value: azureOpenAiDeploymentName
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: azureOpenAiApiVersion
            }
            {
              name: 'AGENT365_ENABLED'
              value: string(agent365Enabled)
            }
            {
              name: 'AGENT365_REQUIRE_AUTH'
              value: string(agent365RequireAuth)
            }
            {
              name: 'AGENT365_CLIENT_ID'
              value: agent365ClientId
            }
            {
              name: 'AGENT365_TENANT_ID'
              value: agent365TenantId
            }
          ], useApiKey ? [
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-api-key'
            }
          ] : [])
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: targetPort
              }
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/readyz'
                port: targetPort
              }
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output agentCardUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}/.well-known/agent-card.json'
output a2aEndpoint string = 'https://${containerApp.properties.configuration.ingress.fqdn}/a2a/v1'
output principalId string = containerApp.identity.principalId
