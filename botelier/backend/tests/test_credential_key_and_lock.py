"""Unit tests for the credential master-key resolution and the per-connection
token-refresh advisory-lock key.

Covers:
  • crypto.get_cipher() — process-lifetime cache, env-var source, Azure Key
    Vault source (mocked), fail-closed on Key Vault error, and production
    fail-fast when no key source is configured.
  • integration_client._advisory_lock_key() — deterministic across processes
    regardless of PYTHONHASHSEED (Python's built-in hash() must NOT be used).
"""

import os
import subprocess
import sys
import uuid
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.fernet import Fernet

from botelier import crypto
from botelier.models.integration import AccountIntegration, IntegrationStatus
from botelier.services.integration_client import IntegrationClient, _advisory_lock_key


class _RaisingAsyncClient:
    """Stand-in for httpx.AsyncClient whose POST always fails transiently."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ConnectError("transient network blip")


_TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _clear_cipher_cache(monkeypatch):
    """Isolate every test from a previously-resolved / cached cipher."""
    monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)
    monkeypatch.delenv("INTEGRATION_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("INTEGRATION_ENCRYPTION_KEY_SECRET_NAME", raising=False)
    monkeypatch.delenv("BOTELIER_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    crypto.reset_cipher_cache()
    yield
    crypto.reset_cipher_cache()


# ── crypto.get_cipher ─────────────────────────────────────────────────────────


def test_get_cipher_returns_cached_instance(monkeypatch):
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", _TEST_KEY)
    first = crypto.get_cipher()
    second = crypto.get_cipher()
    assert first is second  # cached for the process lifetime

    token = first.encrypt(b"secret")
    assert second.decrypt(token) == b"secret"


def test_env_var_multi_key_decrypts_old_ciphertext(monkeypatch):
    old_key = Fernet.generate_key().decode()
    old_cipher = Fernet(old_key.encode())
    ciphertext = old_cipher.encrypt(b"legacy")

    # New primary first, old key as read-only fallback.
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", f"{_TEST_KEY},{old_key}")
    cipher = crypto.get_cipher()

    assert cipher.decrypt(ciphertext) == b"legacy"  # readable via fallback key
    # New writes use the primary key.
    assert cipher.decrypt(cipher.encrypt(b"fresh")) == b"fresh"


def test_key_vault_source_is_used_when_configured(monkeypatch):
    import azure.identity
    import azure.keyvault.secrets

    seen = {}

    class _FakeSecret:
        def __init__(self, value):
            self.value = value

    class _FakeSecretClient:
        def __init__(self, vault_url=None, credential=None):
            seen["vault_url"] = vault_url

        def get_secret(self, name):
            seen["secret_name"] = name
            return _FakeSecret(_TEST_KEY)

    monkeypatch.setattr(
        azure.identity, "DefaultAzureCredential", lambda *a, **k: object()
    )
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", _FakeSecretClient)

    monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://example.vault.azure.net/")
    # env var present too — Key Vault must take precedence.
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", "should-be-ignored")

    cipher = crypto.get_cipher()

    assert seen["vault_url"] == "https://example.vault.azure.net/"
    assert seen["secret_name"] == "integration-encryption-key"  # default name
    assert cipher.decrypt(cipher.encrypt(b"kv")) == b"kv"


def test_key_vault_custom_secret_name(monkeypatch):
    import azure.identity
    import azure.keyvault.secrets

    seen = {}

    class _FakeSecret:
        value = _TEST_KEY

    class _FakeSecretClient:
        def __init__(self, vault_url=None, credential=None):
            pass

        def get_secret(self, name):
            seen["secret_name"] = name
            return _FakeSecret()

    monkeypatch.setattr(
        azure.identity, "DefaultAzureCredential", lambda *a, **k: object()
    )
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", _FakeSecretClient)
    monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://example.vault.azure.net/")
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY_SECRET_NAME", "custom-key")

    crypto.get_cipher()
    assert seen["secret_name"] == "custom-key"


def test_key_vault_failure_fails_closed(monkeypatch):
    import azure.identity
    import azure.keyvault.secrets

    class _BoomClient:
        def __init__(self, vault_url=None, credential=None):
            pass

        def get_secret(self, name):
            raise RuntimeError("vault unreachable")

    monkeypatch.setattr(
        azure.identity, "DefaultAzureCredential", lambda *a, **k: object()
    )
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", _BoomClient)
    monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://example.vault.azure.net/")
    # Even with an env var present, a configured-but-broken vault must NOT fall
    # back — it must raise so the process fails closed.
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", _TEST_KEY)

    with pytest.raises(RuntimeError):
        crypto.get_cipher()


def test_key_vault_empty_secret_raises(monkeypatch):
    import azure.identity
    import azure.keyvault.secrets

    class _EmptySecret:
        value = "   "

    class _EmptyClient:
        def __init__(self, vault_url=None, credential=None):
            pass

        def get_secret(self, name):
            return _EmptySecret()

    monkeypatch.setattr(
        azure.identity, "DefaultAzureCredential", lambda *a, **k: object()
    )
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", _EmptyClient)
    monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://example.vault.azure.net/")

    with pytest.raises(RuntimeError):
        crypto.get_cipher()


def test_production_without_key_source_raises(monkeypatch):
    monkeypatch.setenv("BOTELIER_ENV", "production")
    with pytest.raises(RuntimeError):
        crypto.get_cipher()


def test_dev_generates_ephemeral_key_when_unset(monkeypatch):
    # No key source, not production → ephemeral dev key, no crash.
    cipher = crypto.get_cipher()
    assert cipher.decrypt(cipher.encrypt(b"dev")) == b"dev"


# ── integration_client._advisory_lock_key ─────────────────────────────────────


def test_advisory_lock_key_is_signed_64_bit():
    key = _advisory_lock_key(uuid.uuid4())
    assert isinstance(key, int)
    assert -(2**63) <= key < 2**63  # fits Postgres bigint


def test_advisory_lock_key_accepts_uuid_and_str_equally():
    u = uuid.uuid4()
    assert _advisory_lock_key(u) == _advisory_lock_key(str(u))


def test_advisory_lock_key_is_stable_across_pythonhashseed():
    """hash() is per-process randomized; our key MUST NOT be.

    Compute the key for a fixed UUID in two subprocesses with different
    PYTHONHASHSEED values and assert they match the in-process value.
    """
    fixed = "12345678-1234-5678-1234-567812345678"
    expected = _advisory_lock_key(uuid.UUID(fixed))

    snippet = (
        "import uuid;"
        "from botelier.services.integration_client import _advisory_lock_key;"
        f"print(_advisory_lock_key(uuid.UUID('{fixed}')))"
    )
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    results = []
    for seed in ("0", "1", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.check_output(
            [sys.executable, "-c", snippet], cwd=backend_dir, env=env
        )
        results.append(int(out.strip()))

    assert results[0] == results[1] == results[2] == expected


# ── Transient refresh-failure recovery ────────────────────────────────────────
# execute_request() blocks any integration whose status != CONNECTED BEFORE it
# attempts a refresh. So a transient network error during refresh must NOT write
# a terminal status — otherwise the connection is permanently stuck and can never
# auto-recover. The definitive-rejection (non-200) path stays terminal; only the
# generic exception paths must remain retryable.


@pytest.mark.asyncio
async def test_oauth_transient_exception_keeps_integration_connected(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _RaisingAsyncClient)

    integration = AccountIntegration()
    integration.id = uuid.uuid4()
    integration.status = IntegrationStatus.CONNECTED
    integration.refresh_token_encrypted = None  # -> client_credentials grant

    client = IntegrationClient(account_id="acct-1", db=MagicMock())
    credentials = {
        "gateway_url": "https://sandbox.ocs.oc-test.com",
        "client_id": "cid",
        "client_secret": "csecret",
        "enterprise_id": "ent",
    }
    auth_config = {"token_endpoint_path": "/oauth/v1/tokens"}

    ok = await client._refresh_oauth_token(integration, credentials, auth_config)

    assert ok is False
    assert integration.status == IntegrationStatus.CONNECTED  # still retryable
    assert integration.last_error  # recorded for observability


@pytest.mark.asyncio
async def test_jwt_login_transient_exception_keeps_integration_connected(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _RaisingAsyncClient)

    integration = AccountIntegration()
    integration.id = uuid.uuid4()
    integration.status = IntegrationStatus.CONNECTED
    integration.refresh_token_encrypted = None  # skip refresh branch -> login

    client = IntegrationClient(account_id="acct-1", db=MagicMock())
    credentials = {"username": "u", "password": "p"}
    auth_config = {"base_url": "https://example.test"}

    ok = await client._refresh_jwt_token(integration, credentials, auth_config)

    assert ok is False
    assert integration.status == IntegrationStatus.CONNECTED  # still retryable
    assert integration.last_error
