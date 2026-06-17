"""Botelier credential encryption — single source of truth for all integration secret storage.

Every model that stores credentials at rest (AccountIntegration, MCPConnection,
AccountSecret, and any future models) MUST use get_cipher() from this module.
No other place in the codebase should construct a Fernet or MultiFernet for
credential storage.

──────────────────────────────────────────────────────────────────────────────
Env var:  INTEGRATION_ENCRYPTION_KEY
──────────────────────────────────────────────────────────────────────────────
  Single key (normal):      <url-safe-base64-fernet-key>
  Multi-key (rotation):     <new-primary>,<old-fallback1>,<old-fallback2>

  • The FIRST key in the list is always used for new encryptions.
  • ALL keys are tried in order when decrypting, so credentials encrypted
    with any listed key remain readable until re_encrypt_all() migrates them.

Generate a key:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

──────────────────────────────────────────────────────────────────────────────
Zero-downtime key rotation procedure
──────────────────────────────────────────────────────────────────────────────
  1. Generate a new Fernet key (NEW_KEY).
  2. Set INTEGRATION_ENCRYPTION_KEY = NEW_KEY,CURRENT_KEY
  3. Restart the backend.
     → Old credentials decrypt via CURRENT_KEY; new writes use NEW_KEY.
  4. Call re_encrypt_all(db) to migrate every record to NEW_KEY.
  5. Set INTEGRATION_ENCRYPTION_KEY = NEW_KEY  (remove the old key).
  6. Restart the backend to confirm clean single-key operation.
"""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

_PROD_ENVS = frozenset({"prod", "production"})


def _current_env() -> str:
    return (
        os.environ.get("BOTELIER_ENV")
        or os.environ.get("APP_ENV")
        or os.environ.get("ENVIRONMENT")
        or ""
    ).lower()


def get_cipher() -> MultiFernet:
    """Return the platform-wide credential cipher.

    Reads INTEGRATION_ENCRYPTION_KEY, builds a MultiFernet from the
    comma-separated key list, and returns it.  The first key is the primary
    (used for all new encryptions); subsequent keys are read-only fallbacks
    for records written under older keys.

    Raises RuntimeError in production when the secret is absent.
    In dev/local, auto-generates an ephemeral key (process-lifetime only)
    and emits a prominent warning so developers know to set the secret.
    """
    raw = os.environ.get("INTEGRATION_ENCRYPTION_KEY", "").strip()

    if not raw:
        if _current_env() in _PROD_ENVS:
            raise RuntimeError(
                "INTEGRATION_ENCRYPTION_KEY is required in production. "
                "Generate with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        logger.warning(
            "INTEGRATION_ENCRYPTION_KEY is not set — generating an ephemeral dev key. "
            "Integration credentials will NOT survive a backend restart. "
            "Set this value in Replit Secrets to persist credentials across restarts."
        )
        generated = Fernet.generate_key().decode()
        os.environ["INTEGRATION_ENCRYPTION_KEY"] = generated
        raw = generated

    parts = [k.strip() for k in raw.split(",") if k.strip()]
    if not parts:
        raise RuntimeError("INTEGRATION_ENCRYPTION_KEY is set but contains no valid keys.")

    try:
        keys = [Fernet(p.encode() if isinstance(p, str) else p) for p in parts]
    except Exception as exc:
        raise RuntimeError(
            f"INTEGRATION_ENCRYPTION_KEY contains an invalid Fernet key: {exc}"
        ) from exc

    return MultiFernet(keys)


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
