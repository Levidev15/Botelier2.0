---
name: Credential encryption architecture
description: How Botelier encrypts integration credentials at rest and how key rotation works.
---

## Rule
All credential encryption goes through `botelier/backend/botelier/crypto.py → get_cipher()`.
Every new model that stores secrets at rest MUST import and use `_get_platform_cipher` from there.
No model should ever construct its own `Fernet` or `MultiFernet` for credential storage.

**Why:** Before this was centralised, each model had its own `get_X_encryption_key()` function
with its own env var fallback. MCPConnection had no decryption error handling.  Any key rotation
required finding and updating multiple places.  Centralising gives a single rotation procedure
and guarantees consistent cipher across all current and future integrations.

## How to apply
When adding a new model with encrypted fields:
```python
from botelier.crypto import get_cipher as _get_platform_cipher

class MyModel(Base):
    secret_encrypted = Column(Text, nullable=True)

    def _get_cipher(self):
        return _get_platform_cipher()
```

All encrypt/decrypt calls go through `self._get_cipher()` as before — nothing else changes.
Add the new model's encrypted fields to `crypto.re_encrypt_all()` alongside the existing ones.

## Master-key sources (resolved ONCE per process, then cached)
`get_cipher()` resolves the master key material in this order and caches the built
MultiFernet for the process lifetime (guarded by a lock; Fernet is immutable/thread-safe):
1. **Azure Key Vault** — when `AZURE_KEY_VAULT_URL` is set. Secret name from
   `INTEGRATION_ENCRYPTION_KEY_SECRET_NAME` (default `integration-encryption-key`).
   Auth via managed identity (`DefaultAzureCredential`) — no bootstrap secret on the container.
   **Fails closed:** a configured-but-unreachable vault (or empty/missing secret) RAISES;
   it must NEVER fall back to an ephemeral key (that would orphan every stored credential).
2. `INTEGRATION_ENCRYPTION_KEY` env var (dev / non-Azure).
3. Dev-only ephemeral key (only when not production).

**Why fail-fast at startup:** `main.py` startup calls `get_cipher()` right after DB init so a
misconfigured Key Vault stops the boot (log line `✅ Credential encryption key loaded`),
not the first encrypt/decrypt mid-call.

## Key format (comma-separated Fernet list, both sources)
- Single key:   `<fernet-key>`
- Multi-key:    `<new-primary>,<old-fallback1>,<old-fallback2>`
First key encrypts new values; all keys tried for decryption.

## Zero-downtime rotation
- **Env-var (Replit dev):** set `INTEGRATION_ENCRYPTION_KEY = NEW_KEY,CURRENT_KEY` → restart
  → `re_encrypt_all(db)` → set `= NEW_KEY` → restart.
- **Key Vault (prod voice):** add a new secret VERSION `NEW_KEY,CURRENT_KEY` → roll ALL revisions
  → only THEN `re_encrypt_all(db)` (running it mid-rollout breaks old replicas that lack NEW_KEY)
  → add final version `NEW_KEY` → roll again. Restart re-reads the key (cache is process-lifetime).

## Prod wiring (Azure Container Apps)
`scripts/azure-voice-setup.sh` Step 5b creates the RBAC Key Vault, seeds the secret from the
exported `INTEGRATION_ENCRYPTION_KEY`, assigns the app a system managed identity, grants it
"Key Vault Secrets User", then adds `AZURE_KEY_VAULT_URL` + `BOTELIER_ENV=production` together
(atomic — never "production with no key source"). Requires `azure-identity` +
`azure-keyvault-secrets` (lazy-imported in crypto.py, only when the vault URL is set).

## Dev environment
`INTEGRATION_ENCRYPTION_KEY` is a stable shared env var in Replit (no Key Vault in dev).
Without it the backend generates an ephemeral key per restart — credentials become unreadable
after restart. If decryption failures appear post-restart, check the env var is still present.
