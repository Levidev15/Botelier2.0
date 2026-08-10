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
#   export INTEGRATION_ENCRYPTION_KEY="..."  ← value of INTEGRATION_ENCRYPTION_KEY
#                                              in Replit. One-time only: used to
#                                              seed the Azure Key Vault secret.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
RESOURCE_GROUP="botelier-voice-rg"
LOCATION="eastus"
ACR_NAME="boteliervoiceacr"
ACA_ENV="botelier-voice-env"
ACA_APP="botelier-voice"
CUSTOM_DOMAIN="voice.botelier.ai"
# Credential master key (Fernet) is kept in Key Vault, not as a container secret.
KEY_VAULT_NAME="botelier-voice-kv"
KV_SECRET_NAME="integration-encryption-key"

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
  echo "Container App $ACA_APP already exists — updating image and pinning replicas."
  echo "(To update secrets, use: az containerapp secret set ...)"
  # --min/max-replicas 1 is enforced on EVERY update so pre-existing apps
  # created with the old max-replicas 10 setting are brought into compliance
  # (see the rationale comment on the create branch below).
  az containerapp update \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_LOGIN_SERVER/botelier-voice:latest" \
    --min-replicas 1 \
    --max-replicas 1
  # Verify the deployed revision's scale configuration.
  echo "Current scale config:"
  az containerapp show \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.template.scale" -o json
else
  # max-replicas MUST stay 1 until call state is externalized:
  # CallHandler, is_pipeline_active, the pre-warm cache, and Twilio mark
  # events are all process-local. With >1 replica, Twilio /status,
  # /connect-complete, and transfer callbacks can land on a replica that
  # does not hold the call's WebSocket (teardown silently no-ops), and
  # scale-in kills live calls mid-sentence. The default HTTP-concurrency
  # scale rule would scale on REST traffic, not calls.
  # See docs/azure-voice-task-context.md.
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
    --max-replicas 1
fi

echo ""
echo "=== Step 5b: Azure Key Vault + managed identity (credential master key) ==="
# The Fernet master key that encrypts every stored integration credential is
# kept in Key Vault and read at boot via the container's managed identity — it
# is NOT baked into the container as an env-var secret. See
# botelier/backend/botelier/crypto.py for the resolution + rotation runbook.
#
# Ordering matters: BOTELIER_ENV=production is added ONLY together with
# AZURE_KEY_VAULT_URL (at the end of this step), so the app is never left in a
# "production, no key source" state that would fail-fast on boot.

if az keyvault show --name "$KEY_VAULT_NAME" &>/dev/null; then
  echo "Key Vault $KEY_VAULT_NAME already exists, skipping create."
else
  az keyvault create \
    --name "$KEY_VAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --enable-rbac-authorization true
  echo "Key Vault created (RBAC authorization)."
fi

KEY_VAULT_URL=$(az keyvault show --name "$KEY_VAULT_NAME" --query "properties.vaultUri" -o tsv)
KV_ID=$(az keyvault show --name "$KEY_VAULT_NAME" --query id -o tsv)

# Seed the secret. On an RBAC vault the operator needs data-plane access to
# write it, so grant the signed-in user "Key Vault Secrets Officer" first.
if [ -n "${INTEGRATION_ENCRYPTION_KEY:-}" ]; then
  CURRENT_USER_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")
  if [ -n "$CURRENT_USER_ID" ]; then
    az role assignment create \
      --assignee-object-id "$CURRENT_USER_ID" \
      --assignee-principal-type User \
      --role "Key Vault Secrets Officer" \
      --scope "$KV_ID" &>/dev/null || true
    echo "Waiting 20s for RBAC to propagate before writing the secret..."
    sleep 20
  fi
  az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "$KV_SECRET_NAME" \
    --value "$INTEGRATION_ENCRYPTION_KEY" >/dev/null
  echo "Seeded secret '$KV_SECRET_NAME' from exported INTEGRATION_ENCRYPTION_KEY."
elif az keyvault secret show --vault-name "$KEY_VAULT_NAME" --name "$KV_SECRET_NAME" &>/dev/null; then
  echo "Secret '$KV_SECRET_NAME' already present in Key Vault, keeping it."
else
  echo "!! Secret '$KV_SECRET_NAME' is not in Key Vault and INTEGRATION_ENCRYPTION_KEY"
  echo "!! was not exported. NOT wiring AZURE_KEY_VAULT_URL yet (would fail boot)."
  echo "!! Seed it, then re-run this script:"
  echo "!!   az keyvault secret set --vault-name $KEY_VAULT_NAME \\"
  echo "!!     --name $KV_SECRET_NAME --value '<your INTEGRATION_ENCRYPTION_KEY>'"
  SKIP_KV_WIRING=1
fi

if [ "${SKIP_KV_WIRING:-0}" != "1" ]; then
  # Give the container a system-assigned managed identity and let it READ secrets.
  az containerapp identity assign \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --system-assigned >/dev/null
  PRINCIPAL_ID=$(az containerapp identity show \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --query principalId -o tsv)
  az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets User" \
    --scope "$KV_ID" &>/dev/null || true
  echo "Granted the container identity 'Key Vault Secrets User'."
  echo "Waiting 30s for the role assignment to propagate..."
  sleep 30

  # Add env vars ATOMICALLY: BOTELIER_ENV=production only lands together with
  # AZURE_KEY_VAULT_URL, so the app never boots as "production with no key".
  az containerapp update \
    --name "$ACA_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --set-env-vars \
      "AZURE_KEY_VAULT_URL=$KEY_VAULT_URL" \
      "INTEGRATION_ENCRYPTION_KEY_SECRET_NAME=$KV_SECRET_NAME" \
      "BOTELIER_ENV=production"
  echo "Container App now reads the master key from Key Vault at $KEY_VAULT_URL"
  echo "(If the new revision is unhealthy, RBAC may still be propagating —"
  echo " restart it: az containerapp revision restart --revision <name> ...)"
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
echo "  6. Confirm the master key loaded from Key Vault (boot log line:"
echo "       '✅ Credential encryption key loaded'). To rotate it later, add a"
echo "       new version of the '$KV_SECRET_NAME' secret and roll the revision."
