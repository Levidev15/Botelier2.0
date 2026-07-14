"""Layered runtime for third-party integration API calls.

This package holds the pieces that ``services/integration_client.py`` used to
carry as a single module: shared value types, the JSONPath-lite extractor, log
redaction, the token-refresh advisory-lock helpers, and the ``IntegrationClient``
runtime engine (plus optional per-vendor adapters under ``adapters/``).

``services/integration_client.py`` remains as a pure re-export facade so every
existing import keeps working.
"""
