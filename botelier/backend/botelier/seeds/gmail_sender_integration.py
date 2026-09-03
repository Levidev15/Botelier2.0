"""Seed: Gmail Email Sender integration type.

A platform-certified integration for connecting a Gmail / Google Workspace
mailbox as an outbound email sender. Botelier's own OAuth application
credentials (GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET env vars) are injected
server-side at connect time — account users only click "Connect Gmail".

Category: email_sender
Auth type: oauth2_authorization_code
Scopes: gmail.send + userinfo.email (send-only, least-privilege)
"""

import json

from botelier.models.integration import IntegrationType

GMAIL_SENDER = {
    "slug": "email-sender-gmail",
    "name": "Gmail",
    "description": (
        "Connect a Gmail or Google Workspace account to send emails on behalf "
        "of your business. Uses send-only permissions — Botelier cannot read "
        "your messages."
    ),
    "provider": "google",
    "auth_type": "oauth2_authorization_code",
    "category": "email_sender",
    "documentation_url": "https://developers.google.com/gmail/api/guides/sending",
    "auth_config": {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "base_url": "https://gmail.googleapis.com",
        "scope": (
            "https://www.googleapis.com/auth/gmail.send "
            "https://www.googleapis.com/auth/userinfo.email "
            "openid"
        ),
        # Tell Google to return a refresh token so the connection stays alive
        "extra_authorize_params": {
            "access_type": "offline",
            "prompt": "consent",
        },
        # Endpoint used after OAuth to fetch the connected email address
        "userinfo_endpoint": "https://www.googleapis.com/oauth2/v2/userinfo",
        "userinfo_email_field": "email",
    },
    # No user-facing required_fields — platform credentials are injected server-side
    "required_fields": [],
    # One placeholder endpoint satisfies the seed validator
    "endpoints_config": [
        {
            "id": "send_message",
            "name": "Send Message",
            "path": "/gmail/v1/users/me/messages/send",
            "method": "POST",
            "category": "Email",
            "description": "Send an email from the connected Gmail account.",
        }
    ],
}


def seed_gmail_sender_integration(db_session) -> None:
    """Upsert the Gmail email sender integration type. Idempotent."""
    existing = (
        db_session.query(IntegrationType)
        .filter_by(slug=GMAIL_SENDER["slug"])
        .first()
    )

    if existing:
        existing.name = GMAIL_SENDER["name"]
        existing.description = GMAIL_SENDER["description"]
        existing.provider = GMAIL_SENDER["provider"]
        existing.auth_type = GMAIL_SENDER["auth_type"]
        existing.documentation_url = GMAIL_SENDER["documentation_url"]
        existing.is_enabled = True
        existing.set_auth_config(GMAIL_SENDER["auth_config"])
        existing.set_required_fields(GMAIL_SENDER["required_fields"])
        existing.set_endpoints(GMAIL_SENDER["endpoints_config"])
        # Set category column if present on the model
        if hasattr(existing, "category"):
            existing.category = GMAIL_SENDER["category"]
        db_session.commit()
        print(f"Updated Gmail sender integration type: {existing.id}")
    else:
        kwargs = dict(
            slug=GMAIL_SENDER["slug"],
            name=GMAIL_SENDER["name"],
            description=GMAIL_SENDER["description"],
            provider=GMAIL_SENDER["provider"],
            auth_type=GMAIL_SENDER["auth_type"],
            documentation_url=GMAIL_SENDER["documentation_url"],
            is_enabled=True,
        )
        if hasattr(IntegrationType, "category"):
            kwargs["category"] = GMAIL_SENDER["category"]
        it = IntegrationType(**kwargs)
        it.set_auth_config(GMAIL_SENDER["auth_config"])
        it.set_required_fields(GMAIL_SENDER["required_fields"])
        it.set_endpoints(GMAIL_SENDER["endpoints_config"])
        db_session.add(it)
        db_session.commit()
        print(f"Created Gmail sender integration type: {it.id}")
