"""Seed: Microsoft Email Sender integration type.

A platform-certified integration for connecting a Microsoft 365 / Outlook
mailbox as an outbound email sender. Botelier's own OAuth application
credentials (MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET env vars) are
injected server-side at connect time — account users only click
"Connect Microsoft".

Category: email_sender
Auth type: oauth2_authorization_code
Scopes: Mail.Send + User.Read + offline_access (send-only, least-privilege)
"""

from botelier.models.integration import IntegrationType

MICROSOFT_SENDER = {
    "slug": "email-sender-microsoft",
    "name": "Microsoft / Outlook",
    "description": (
        "Connect a Microsoft 365 or Outlook account to send emails on behalf "
        "of your business. Uses send-only permissions — Botelier cannot read "
        "your messages."
    ),
    "provider": "microsoft",
    "auth_type": "oauth2_authorization_code",
    "category": "email_sender",
    "documentation_url": "https://learn.microsoft.com/en-us/graph/api/user-sendmail",
    "auth_config": {
        # common tenant supports both personal and work/school accounts
        "authorization_endpoint": (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        ),
        "token_endpoint": (
            "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        ),
        "base_url": "https://graph.microsoft.com",
        # offline_access gives a refresh token
        "scope": "Mail.Send User.Read offline_access",
        # Endpoint used after OAuth to fetch the connected email address
        "userinfo_endpoint": "https://graph.microsoft.com/v1.0/me",
        "userinfo_email_field": "mail",
        "userinfo_email_fallback_field": "userPrincipalName",
    },
    "required_fields": [],
    "endpoints_config": [
        {
            "id": "send_mail",
            "name": "Send Mail",
            "path": "/v1.0/me/sendMail",
            "method": "POST",
            "category": "Email",
            "description": "Send an email from the connected Microsoft account.",
        }
    ],
}


def seed_microsoft_sender_integration(db_session) -> None:
    """Upsert the Microsoft email sender integration type. Idempotent."""
    existing = (
        db_session.query(IntegrationType)
        .filter_by(slug=MICROSOFT_SENDER["slug"])
        .first()
    )

    if existing:
        existing.name = MICROSOFT_SENDER["name"]
        existing.description = MICROSOFT_SENDER["description"]
        existing.provider = MICROSOFT_SENDER["provider"]
        existing.auth_type = MICROSOFT_SENDER["auth_type"]
        existing.documentation_url = MICROSOFT_SENDER["documentation_url"]
        existing.is_enabled = True
        existing.set_auth_config(MICROSOFT_SENDER["auth_config"])
        existing.set_required_fields(MICROSOFT_SENDER["required_fields"])
        existing.set_endpoints(MICROSOFT_SENDER["endpoints_config"])
        if hasattr(existing, "category"):
            existing.category = MICROSOFT_SENDER["category"]
        db_session.commit()
        print(f"Updated Microsoft sender integration type: {existing.id}")
    else:
        kwargs = dict(
            slug=MICROSOFT_SENDER["slug"],
            name=MICROSOFT_SENDER["name"],
            description=MICROSOFT_SENDER["description"],
            provider=MICROSOFT_SENDER["provider"],
            auth_type=MICROSOFT_SENDER["auth_type"],
            documentation_url=MICROSOFT_SENDER["documentation_url"],
            is_enabled=True,
        )
        if hasattr(IntegrationType, "category"):
            kwargs["category"] = MICROSOFT_SENDER["category"]
        it = IntegrationType(**kwargs)
        it.set_auth_config(MICROSOFT_SENDER["auth_config"])
        it.set_required_fields(MICROSOFT_SENDER["required_fields"])
        it.set_endpoints(MICROSOFT_SENDER["endpoints_config"])
        db_session.add(it)
        db_session.commit()
        print(f"Created Microsoft sender integration type: {it.id}")
