#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# azure-voice-setup.sh
#
# One-time setup script for the Botelier voice backend on Azure Container Apps.
# Safe to re-run — all steps check for existing resources before creating them.
#
# Run from Azure Cloud Shell (or local machine with az CLI installed):
#   chmod +x scripts/azure-voice-setup.sh
#   ./scripts/azure-voice-setup.sh
#
# Export these before running (values come from your Replit Secrets panel):
#   export DATABASE_URL="..."        ← value of NEON_DATABASE_URL in Replit
#   export NEXTAUTH_SECRET="..."     ← value of NEXTAUTH_SECRET in Replit
#   export TWILIO_AUTH_TOKEN="..."
#   export TWILIO_ACCOUNT_SID="..."
#   export DEEPGRAM_API_KEY="..."
#   export OPENAI_API_KEY="..."
#   export STREAM_TOKEN_SECRET=""    ← optional, leave empty string if not set
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
RESOURCE_GROUP="botelier-voice-rg"
LOCATION="eastus"
ACR_NAME="boteliervoiceacr"
ACA_ENV="botelier-voice-env"
ACA_APP="botelier-voice"
CUSTOM_DOMAIN="voice.botelier.ai"

# ── Validate required secrets ─────────────────────────────────────────────────
: "${DATABASE_URL:?DATABASE_URL must be set (use NEON_DATABASE_URL value from Replit)}"
: "${NEXTAUTH_SECRET:?NEXTAUTH_SECRET must be set (from Replit Configurations panel)}"
: "${TWILIO_AUTH_TOKEN:?TWILIO_AUTH_TOKEN must be set}"
: "${TWILIO_ACCOUNT_SID:?TWILIO_ACCOUNT_SID must be set}"
: "${DEEPGRAM_API_KEY:?DEEPGRAM_API_KEY must be set}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"

# Optional — backend falls back to TWILIO_AUTH_TOKEN if absent
STREAM_TOKEN_SECRET="${STREAM_TOKEN_SECRET:-}"

# ─────────────────────────────────────────────────────────────────────────────

echo "=== Step 1: Resource Group ==="
if az group show --name "$RESOURCE_GROUP" &>/dev/null; then
  echo "Resource group $RESOURCE_GROUP already exists, skipping."
else
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
  echo "Resource group created."
fi

echo ""
echo "=== Step 2: Azure Container Registry ==="
if az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Container registry $ACR_NAME already exists, skipping."
else
  az acr create \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --sku Basic \
    --admin-enabled true
  echo "Container registry created."
fi

ACR_LOGIN_SERVER=$(az acr show \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query loginServer -o tsv)

echo "ACR login server: $ACR_LOGIN_SERVER"

echo ""
echo "=== Step 3: Build and push initial image ==="
# Build context is repo root so the Dockerfile can COPY both
# botelier/backend/ and src/pipecat/ (which lives at repo root level).
az acr build \
  --registry "$ACR_NAME" \
  --image "botelier-voice:latest" \
  --file "botelier/backend/Dockerfile" \
  .

echo ""
echo "=== Step 4: Container Apps Environment ==="
if az containerapp env show --name "$ACA_ENV" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Container Apps environment $ACA_ENV already exists, skipping."
else
  az containerapp env create \
    --name "$ACA_ENV" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION"
  echo "Container Apps environment created."
fi

echo ""
echo "=== Step 5: Container App ==="
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query 'passwords[0].value' -o tsv)

# Build the secrets and env-vars arrays — STREAM_TOKEN_SECRET is optional
SECRETS_LIST=(
  "database-url=$DATABASE_URL"
  "nextauth-secret=$NEXTAUTH_SECRET"
  "twilio-auth-token=$TWILIO_AUTH_TOKEN"
  "twilio-account-sid=$TWILIO_ACCOUNT_SID"
  "deepgram-api-key=$DEEPGRAM_API_KEY"
  "openai-api-key=$OPENAI_API_KEY"
)
ENV_VARS_LIST=(
  "DATABASE_URL=secretref:database-url"
  "NEXTAUTH_SECRET=secretref:nextauth-secret"
  "TWILIO_AUTH_TOKEN=secretref:twilio-auth-token"
  "TWILIO_ACCOUNT_SID=secretref:twilio-account-sid"
  "DEEPGRAM_API_KEY=secretref:deepgram-api-key"
  "OPENAI_API_KEY=secretref:openai-api-key"
  "PUBLIC_BASE_URL=https://$CUSTOM_DOMAIN"
  "BACKEND_WS_URL=wss://$CUSTOM_DOMAIN"
  "LOG_LEVEL=INFO"
  "DB_POOL_SIZE=5"
  "DB_MAX_OVERFLOW=10"
)

if [ -n "$STREAM_TOKEN_SECRET" ]; then
  SECRETS_LIST+=("stream-token-secret=$STREAM_TOKEN_SECRET")
  ENV_VARS_LIST+=("STREAM_TOKEN_SECRET=secretref:stream-token-secret")
fi

if az containerapp show --name "$ACA_APP" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Container App $ACA_APP already exists — updating image only."
  echo "(To update secrets, use: az containerapp secret set ...)"
  az containerapp update \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_LOGIN_SERVER/botelier-voice:latest"
else
  az containerapp create \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ACA_ENV" \
    --image "$ACR_LOGIN_SERVER/botelier-voice:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 8000 \
    --ingress external \
    --secrets "${SECRETS_LIST[@]}" \
    --env-vars "${ENV_VARS_LIST[@]}" \
    --cpu 1.0 \
    --memory 2.0Gi \
    --min-replicas 1 \
    --max-replicas 10
fi

echo ""
echo "=== Step 6: Ingress — WebSocket requires transport=http ==="
# CRITICAL: 'auto' defaults to HTTP/2 which lacks the HTTP/1.1 Upgrade
# mechanism required for WebSocket handshakes — Twilio media streams break.
az containerapp ingress update \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --transport http

echo ""
echo "=== Step 7: Sticky sessions ==="
# REQUIRED: CallHandler pre-warm cache is in-memory. The /incoming webhook
# and the WebSocket upgrade that follows MUST hit the same replica.
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
read -r -p "Press Enter once the DNS CNAME is live (may take a few minutes to propagate)..."

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
echo "Add these 6 secrets to your GitHub repo:"
echo "(GitHub repo → Settings → Secrets and variables → Actions → New repository secret)"
echo ""
echo "  AZURE_CREDENTIALS    → run this and paste the full JSON output:"
echo "                         az ad sp create-for-rbac --name botelier-voice-deploy --sdk-auth"
echo ""
echo "  ACR_LOGIN_SERVER     → $ACR_LOGIN_SERVER"
echo "  ACR_USERNAME         → $ACR_USERNAME"
echo "  ACR_PASSWORD         → $ACR_PASSWORD"
echo "  ACA_APP_NAME         → $ACA_APP"
echo "  ACA_RESOURCE_GROUP   → $RESOURCE_GROUP"
echo ""

echo "=== Setup complete ==="
echo ""
echo "Voice backend URL:  https://$CUSTOM_DOMAIN"
echo "Health check:       https://$CUSTOM_DOMAIN/api/health"
echo ""
echo "Next steps:"
echo "  1. Add the 6 GitHub Actions secrets printed above"
echo "  2. Verify: curl https://$CUSTOM_DOMAIN/api/health"
echo "  3. Update Twilio webhook for +1 702 935 1117 (Mrs Fields):"
echo "       Voice URL: https://$CUSTOM_DOMAIN/api/calls/incoming"
echo "  4. Update Twilio webhook for +1 725 444 6079 (AVA-PV):"
echo "       Voice URL: https://$CUSTOM_DOMAIN/api/calls/incoming"
echo "  5. Make a test production call and confirm no audio choppiness."
