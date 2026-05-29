#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# azure-voice-setup.sh
#
# One-time setup script for the Botelier voice backend on Azure Container Apps.
# Run this once from your local machine (or Azure Cloud Shell) with the Azure
# CLI installed and logged in (az login).
#
# Usage:
#   chmod +x scripts/azure-voice-setup.sh
#   ./scripts/azure-voice-setup.sh
#
# Prerequisites:
#   - Azure CLI installed: https://learn.microsoft.com/cli/azure/install-azure-cli
#   - Logged in: az login
#   - Subscription set: az account set --subscription "<your-subscription>"
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration — edit these before running ────────────────────────────────
RESOURCE_GROUP="botelier-voice-rg"
LOCATION="eastus"                        # Azure region — pick closest to users
ACR_NAME="boteliervoiceacr"              # Must be globally unique, alphanumeric
ACA_ENV="botelier-voice-env"
ACA_APP="botelier-voice"
CUSTOM_DOMAIN="voice.botelier.ai"

# These will be read from environment variables at runtime — never hardcoded.
# Set them in your shell before running, or edit the --secrets block below.
: "${DATABASE_URL:?DATABASE_URL must be set}"
: "${SECRET_KEY:?SECRET_KEY must be set}"
: "${STREAM_TOKEN_SECRET:?STREAM_TOKEN_SECRET must be set}"
: "${TWILIO_AUTH_TOKEN:?TWILIO_AUTH_TOKEN must be set}"
: "${TWILIO_ACCOUNT_SID:?TWILIO_ACCOUNT_SID must be set}"
: "${DEEPGRAM_API_KEY:?DEEPGRAM_API_KEY must be set}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"
# ─────────────────────────────────────────────────────────────────────────────

echo "=== Step 1: Resource Group ==="
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"

echo ""
echo "=== Step 2: Azure Container Registry ==="
az acr create \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --sku Basic \
  --admin-enabled true

ACR_LOGIN_SERVER=$(az acr show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query loginServer -o tsv)

echo "ACR login server: $ACR_LOGIN_SERVER"

echo ""
echo "=== Step 3: Build and push initial image ==="
# Build from repo root (Dockerfile copies both botelier/backend/ and src/pipecat/)
az acr build \
  --registry "$ACR_NAME" \
  --image "botelier-voice:latest" \
  --file "botelier/backend/Dockerfile" \
  .

echo ""
echo "=== Step 4: Container Apps Environment ==="
az containerapp env create \
  --name "$ACA_ENV" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

echo ""
echo "=== Step 5: Container App ==="
# Secrets are stored in ACA's secret store — never in env vars directly.
az containerapp create \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ACA_ENV" \
  --image "$ACR_LOGIN_SERVER/botelier-voice:latest" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-username "$(az acr credential show --name $ACR_NAME --query username -o tsv)" \
  --registry-password "$(az acr credential show --name $ACR_NAME --query 'passwords[0].value' -o tsv)" \
  --target-port 8000 \
  --ingress external \
  --secrets \
    database-url="$DATABASE_URL" \
    secret-key="$SECRET_KEY" \
    stream-token-secret="$STREAM_TOKEN_SECRET" \
    twilio-auth-token="$TWILIO_AUTH_TOKEN" \
    twilio-account-sid="$TWILIO_ACCOUNT_SID" \
    deepgram-api-key="$DEEPGRAM_API_KEY" \
    openai-api-key="$OPENAI_API_KEY" \
  --env-vars \
    DATABASE_URL=secretref:database-url \
    SECRET_KEY=secretref:secret-key \
    STREAM_TOKEN_SECRET=secretref:stream-token-secret \
    TWILIO_AUTH_TOKEN=secretref:twilio-auth-token \
    TWILIO_ACCOUNT_SID=secretref:twilio-account-sid \
    DEEPGRAM_API_KEY=secretref:deepgram-api-key \
    OPENAI_API_KEY=secretref:openai-api-key \
    PUBLIC_BASE_URL="https://$CUSTOM_DOMAIN" \
    BACKEND_WS_URL="wss://$CUSTOM_DOMAIN" \
    LOG_LEVEL=INFO \
    DB_POOL_SIZE=5 \
    DB_MAX_OVERFLOW=10 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --min-replicas 1 \
  --max-replicas 10

echo ""
echo "=== Step 6: Ingress — WebSocket requires transport=http ==="
# CRITICAL: 'auto' defaults to HTTP/2 which lacks the HTTP/1.1 Upgrade
# mechanism required for WebSocket handshakes — Twilio media streams break.
az containerapp ingress update \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --transport http

echo ""
echo "=== Step 7: Sticky sessions (session affinity) ==="
# REQUIRED: CallHandler pre-warm cache is in-memory. The /incoming webhook
# and the WebSocket upgrade that follows MUST hit the same replica.
# ACA sticky sessions set a cookie on the first HTTP response; all subsequent
# requests (including the Twilio WS upgrade) route to the same replica.
az containerapp ingress sticky-sessions set \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --affinity sticky

echo ""
echo "=== Step 8: Custom domain + managed TLS certificate ==="
echo "Add this CNAME to your DNS before proceeding:"
ACA_FQDN=$(az containerapp show \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo ""
echo "  $CUSTOM_DOMAIN  CNAME  $ACA_FQDN"
echo ""
read -p "Press Enter once the DNS CNAME is live (may take a few minutes to propagate)..."

az containerapp hostname add \
  --hostname "$CUSTOM_DOMAIN" \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP"

# Azure provisions a free managed TLS certificate and auto-renews it.
az containerapp hostname bind \
  --hostname "$CUSTOM_DOMAIN" \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ACA_ENV" \
  --validation-method CNAME

echo ""
echo "=== Step 9: GitHub Actions secrets ==="
echo "Add these secrets to your GitHub repository (Settings → Secrets → Actions):"
echo ""
echo "  AZURE_CREDENTIALS    → output of: az ad sp create-for-rbac --sdk-auth"
echo "  ACR_LOGIN_SERVER     → $ACR_LOGIN_SERVER"
echo "  ACR_USERNAME         → $(az acr credential show --name $ACR_NAME --query username -o tsv)"
echo "  ACR_PASSWORD         → (from: az acr credential show --name $ACR_NAME)"
echo "  ACA_APP_NAME         → $ACA_APP"
echo "  ACA_RESOURCE_GROUP   → $RESOURCE_GROUP"
echo ""

echo "=== Setup complete ==="
echo ""
echo "Voice backend URL:  https://$CUSTOM_DOMAIN"
echo "Health check:       https://$CUSTOM_DOMAIN/api/health"
echo ""
echo "Next steps:"
echo "  1. Verify health: curl https://$CUSTOM_DOMAIN/api/health"
echo "  2. Update Twilio webhook for +1 702 935 1117 (Mrs Fields):"
echo "       Voice: https://$CUSTOM_DOMAIN/api/calls/incoming"
echo "  3. Update Twilio webhook for +1 725 444 6079 (AVA-PV):"
echo "       Voice: https://$CUSTOM_DOMAIN/api/calls/incoming"
echo "  4. Make a test production call and confirm no audio choppiness."
