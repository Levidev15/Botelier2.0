"""Botelier credential encryption — single source of truth for all integration secret storage.

Every model that stores credentials at rest (AccountIntegration, MCPConnection,
AccountSecret, and any future models) MUST use get_cipher() from this module.
No other place in the codebase should construct a Fernet or MultiFernet for
credential storage.

──────────────────────────────────────────────────────────────────────────────
Master-key sources (resolved once per process, then cached)
──────────────────────────────────────────────────────────────────────────────
The master key material is a comma-separated list of url-safe base64 Fernet
keys.  The FIRST key is always used for new encryptions; ALL keys are tried in
order when decrypting, so credentials written under any listed key stay readable
until re_encrypt_all() migrates them.

  Single key (normal):      <fernet-key>
  Multi-key (rotation):     <new-primary>,<old-fallback1>,<old-fallback2>

Resolution order (first match wins), evaluated ONCE per process at first use:

  1. Azure Key Vault — when AZURE_KEY_VAULT_URL is set.
       • Secret name from INTEGRATION_ENCRYPTION_KEY_SECRET_NAME
         (default "integration-encryption-key").
       • Authenticates with a managed identity via DefaultAzureCredential —
         no bootstrap secret lives on the container.
       • Fails CLOSED: if the vault is configured but unreachable / the secret
         is missing, startup raises rather than falling back to an ephemeral
         key that would orphan every stored credential.
  2. INTEGRATION_ENCRYPTION_KEY env var — the dev / non-Azure path.
  3. Dev-only ephemeral key — generated when neither of the above is present
     AND the environment is not production.  Never used in production.

The resolved key material and the built MultiFernet are cached at module scope
for the life of the process (Fernet objects are immutable and thread-safe), so
get_cipher() never re-hits Key Vault after the first call.  Because rotation
already requires a restart, the process-lifetime cache changes nothing about
the rotation contract.

Generate a key:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

──────────────────────────────────────────────────────────────────────────────
Zero-downtime key rotation procedure
──────────────────────────────────────────────────────────────────────────────
  Env-var deployments (Replit dev):
    1. Generate a new Fernet key (NEW_KEY).
    2. Set INTEGRATION_ENCRYPTION_KEY = NEW_KEY,CURRENT_KEY
    3. Restart the backend.
       → Old credentials decrypt via CURRENT_KEY; new writes use NEW_KEY.
    4. Call re_encrypt_all(db) to migrate every record to NEW_KEY.
    5. Set INTEGRATION_ENCRYPTION_KEY = NEW_KEY  (remove the old key).
    6. Restart the backend to confirm clean single-key operation.

  Azure Key Vault deployments (production voice):
    1. Generate a new Fernet key (NEW_KEY).
    2. Add a new version of the Key Vault secret with value NEW_KEY,CURRENT_KEY.
    3. Restart / roll the Container App revision so every replica re-reads it.
       → Old credentials decrypt via CURRENT_KEY; new writes use NEW_KEY.
    4. Once ALL replicas are on the new revision, call re_encrypt_all(db)
       (do NOT run it mid-rollout — old replicas would still hold only the old
       key and could not read records the new replicas re-keyed).
    5. Add a final secret version with value NEW_KEY only.
    6. Restart / roll the revision to confirm clean single-key operation.
"""

import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

_PROD_ENVS = frozenset({"prod", "production"})

_DEFAULT_KEY_VAULT_SECRET_NAME = "integration-encryption-key"

# The master key is resolved once per process and reused for every encrypt /
# decrypt.  Guarded by a lock so concurrent first-callers (uvicorn threadpool +
# async) never trigger duplicate Key Vault fetches.
_cache_lock = threading.Lock()
_cached_cipher: "MultiFernet | None" = None
_cached_key_material: "str | None" = None


def _current_env() -> str:
    return (
        os.environ.get("BOTELIER_ENV")
        or os.environ.get("APP_ENV")
        or os.environ.get("ENVIRONMENT")
        or ""
    ).lower()


def _fetch_key_material_from_key_vault(vault_url: str, secret_name: str) -> str:
    """Fetch the master-key material from Azure Key Vault via managed identity.

    Raises RuntimeError on any failure — callers MUST fail closed rather than
    fall back to an ephemeral key that would orphan every stored credential.
    The Azure SDK is imported lazily so dev environments without the packages
    (and without AZURE_KEY_VAULT_URL) never need them installed.
    """
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as exc:  # pragma: no cover - depends on deploy image
        raise RuntimeError(
            "AZURE_KEY_VAULT_URL is set but the Azure SDK is not installed. "
            "Add 'azure-identity' and 'azure-keyvault-secrets' to requirements.txt."
        ) from exc

    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        secret = client.get_secret(secret_name)
    except Exception as exc:  # pragma: no cover - network / auth dependent
        raise RuntimeError(
            f"Failed to fetch encryption key secret '{secret_name}' from Azure "
            f"Key Vault at {vault_url}: {exc}"
        ) from exc

    value = (secret.value or "").strip()
    if not value:
        raise RuntimeError(
            f"Azure Key Vault secret '{secret_name}' is empty — cannot build cipher."
        )
    return value


def _resolve_key_material() -> str:
    """Resolve the raw master-key string (comma-separated Fernet key list).

    See the module docstring for the full resolution order.  Raises
    RuntimeError when a configured source fails or when production has no key.
    """
    vault_url = os.environ.get("AZURE_KEY_VAULT_URL", "").strip()
    if vault_url:
        secret_name = (
            os.environ.get("INTEGRATION_ENCRYPTION_KEY_SECRET_NAME", "").strip()
            or _DEFAULT_KEY_VAULT_SECRET_NAME
        )
        logger.info(
            "Resolving integration encryption key from Azure Key Vault "
            "(secret '%s').",
            secret_name,
        )
        return _fetch_key_material_from_key_vault(vault_url, secret_name)

    raw = os.environ.get("INTEGRATION_ENCRYPTION_KEY", "").strip()
    if raw:
        return raw

    if _current_env() in _PROD_ENVS:
        raise RuntimeError(
            "No integration encryption key configured in production. Set "
            "AZURE_KEY_VAULT_URL (preferred) or INTEGRATION_ENCRYPTION_KEY. "
            "Generate a key with: python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\""
        )

    logger.warning(
        "No integration encryption key configured — generating an ephemeral "
        "dev key. Integration credentials will NOT survive a backend restart. "
        "Set INTEGRATION_ENCRYPTION_KEY in Replit Secrets to persist them."
    )
    return Fernet.generate_key().decode()


def _build_cipher(raw: str) -> MultiFernet:
    parts = [k.strip() for k in raw.split(",") if k.strip()]
    if not parts:
        raise RuntimeError("Encryption key material is set but contains no valid keys.")
    try:
        keys = [Fernet(p.encode() if isinstance(p, str) else p) for p in parts]
    except Exception as exc:
        raise RuntimeError(
            f"Encryption key material contains an invalid Fernet key: {exc}"
        ) from exc
    return MultiFernet(keys)


def get_cipher() -> MultiFernet:
    """Return the platform-wide credential cipher (cached for the process).

    On first call the master key is resolved from Azure Key Vault or the
    INTEGRATION_ENCRYPTION_KEY env var (see module docstring), a MultiFernet is
    built, and both are cached.  Subsequent calls return the cached cipher
    without touching Key Vault or the environment.

    Raises RuntimeError when a configured Key Vault is unreachable, when the
    key material is invalid, or when production has no key source.  Call this
    early at startup so a misconfiguration fails the boot instead of the first
    encrypt/decrypt.
    """
    global _cached_cipher, _cached_key_material

    if _cached_cipher is not None:
        return _cached_cipher

    with _cache_lock:
        if _cached_cipher is not None:
            return _cached_cipher
        raw = _resolve_key_material()
        cipher = _build_cipher(raw)
        _cached_key_material = raw
        _cached_cipher = cipher
        return _cached_cipher


def reset_cipher_cache() -> None:
    """Clear the cached cipher/key material. Intended for tests only."""
    global _cached_cipher, _cached_key_material
    with _cache_lock:
        _cached_cipher = None
        _cached_key_material = None


def re_encrypt_all(db) -> dict:
    """Re-encrypt every credential field across all models using the current primary key.

    Call this after step 4 of the rotation procedure (see module docstring).
    Once it returns successfully you can safely remove the old fallback key
    from INTEGRATION_ENCRYPTION_KEY and restart the backend.

    Returns a summary of how many records were re-keyed per model:
      {"AccountIntegration": n, "MCPConnection": n, "AccountSecret": n}
    """
    from botelier.models.integration import AccountIntegration, AccountSecret
    from botelier.models.mcp_connection import MCPConnection

    cipher = get_cipher()
    summary: dict[str, int] = {}

    def _rekey(label: str, ciphertext: str | None, row_id) -> str | None:
        """Decrypt with any listed key, re-encrypt with the primary key."""
        if not ciphertext:
            return ciphertext
        try:
            plaintext = cipher.decrypt(ciphertext.encode())
            return cipher.encrypt(plaintext).decode()
        except InvalidToken:
            logger.warning(
                "re_encrypt_all: %s id=%s — ciphertext unreadable with current key list; "
                "leaving unchanged.  Add the original key back to INTEGRATION_ENCRYPTION_KEY "
                "and retry.",
                label,
                row_id,
            )
            return ciphertext

    # ── AccountIntegration: credentials, access_token, refresh_token ──────────
    count = 0
    for row in db.query(AccountIntegration).all():
        before = (row.credentials_encrypted, row.access_token_encrypted, row.refresh_token_encrypted)
        row.credentials_encrypted = _rekey(
            "AccountIntegration.credentials", row.credentials_encrypted, row.id
        )
        row.access_token_encrypted = _rekey(
            "AccountIntegration.access_token", row.access_token_encrypted, row.id
        )
        row.refresh_token_encrypted = _rekey(
            "AccountIntegration.refresh_token", row.refresh_token_encrypted, row.id
        )
        after = (row.credentials_encrypted, row.access_token_encrypted, row.refresh_token_encrypted)
        if before != after:
            count += 1
    summary["AccountIntegration"] = count

    # ── MCPConnection: credentials ────────────────────────────────────────────
    count = 0
    for row in db.query(MCPConnection).all():
        orig = row.credentials_encrypted
        row.credentials_encrypted = _rekey(
            "MCPConnection.credentials", row.credentials_encrypted, row.id
        )
        if row.credentials_encrypted != orig:
            count += 1
    summary["MCPConnection"] = count

    # ── AccountSecret: value ──────────────────────────────────────────────────
    count = 0
    for row in db.query(AccountSecret).all():
        orig = row.value_encrypted
        row.value_encrypted = _rekey("AccountSecret.value", row.value_encrypted, row.id)
        if row.value_encrypted != orig:
            count += 1
    summary["AccountSecret"] = count

    db.commit()
    logger.info("re_encrypt_all complete — re-keyed records: %s", summary)
    return summary
