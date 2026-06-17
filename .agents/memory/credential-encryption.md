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

## Key format (INTEGRATION_ENCRYPTION_KEY env var)
- Single key:   `<fernet-key>`
- Multi-key:    `<new-primary>,<old-fallback1>,<old-fallback2>`

First key encrypts new values; all keys tried for decryption.

## Zero-downtime rotation
1. Generate `NEW_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Set `INTEGRATION_ENCRYPTION_KEY = NEW_KEY,CURRENT_KEY` and restart.
3. Call `re_encrypt_all(db)` (admin endpoint or management script).
4. Set `INTEGRATION_ENCRYPTION_KEY = NEW_KEY` and restart.

## Dev environment
`INTEGRATION_ENCRYPTION_KEY` is set as a stable shared env var in Replit.
Without it the backend generates an ephemeral key per process restart — all credentials
become unreadable after restart. If decryption failures appear after a restart, check
that the env var is still present and has not been accidentally deleted.
