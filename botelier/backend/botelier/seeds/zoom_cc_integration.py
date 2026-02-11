"""
Zoom Contact Center Integration Seed Data.

This seeds the IntegrationType for Zoom Contact Center with proper API
configuration including OAuth 2.0 Server-to-Server auth and pre-built
endpoint templates for queue performance, agent metrics, and call analytics.
"""

import json
from botelier.models.integration import IntegrationType


ZOOM_CC_INTEGRATION = {
    "slug": "zoom-contact-center",
    "name": "Zoom Contact Center",
    "description": "Connect to Zoom Contact Center for queue performance reports, agent metrics, and call analytics.",
    "logo_url": "/integrations/zoom-cc-logo.png",
    "provider": "zoom",
    "auth_type": "oauth2_client_credentials",
    "documentation_url": "https://developers.zoom.us/docs/api/contact-center/",
    
    "auth_config": {
        "token_endpoint": "https://zoom.us/oauth/token",
        "grant_type": "account_credentials",
        "scope": "contact_center:read:admin contact_center_analytics:read:admin",
        "token_header": "Authorization",
        "token_prefix": "Bearer",
        "token_request_params": {
            "account_id": "{{account_id}}"
        },
        "auth_method": "basic",
        "basic_auth_fields": ["client_id", "client_secret"]
    },
    
    "required_fields": [
        {
            "key": "account_id",
            "label": "Account ID",
            "type": "text",
            "placeholder": "Your Zoom Account ID",
            "description": "Your Zoom Account ID from the Server-to-Server OAuth app",
            "required": True
        },
        {
            "key": "client_id",
            "label": "Client ID",
            "type": "text",
            "placeholder": "OAuth Client ID",
            "description": "OAuth Client ID from Zoom Marketplace app",
            "required": True
        },
        {
            "key": "client_secret",
            "label": "Client Secret",
            "type": "password",
            "placeholder": "Your OAuth Client Secret",
            "description": "OAuth Client Secret",
            "required": True
        }
    ],
    
    "endpoints": [
        {
            "id": "list_queues",
            "category": "Queues",
            "name": "List Contact Center Queues",
            "description": "List all contact center queues",
            "method": "GET",
            "path": "/v2/contact_center/queues",
            "query_params": [],
            "variables": [],
            "response_mapping": {
                "queues": "$.queues",
                "count": "$.total_records"
            }
        },
        {
            "id": "queue_metrics",
            "category": "Analytics",
            "name": "Queue Historical Metrics",
            "description": "Historical queue metrics with date range",
            "method": "GET",
            "path": "/v2/contact_center/analytics/historical/queues/{{queue_id}}/metrics",
            "query_params": [
                {"key": "from", "value": "{{from_date}}", "required": True},
                {"key": "to", "value": "{{to_date}}", "required": True}
            ],
            "variables": [
                {"key": "queue_id", "type": "text", "label": "Queue ID", "description": "The queue ID", "required": True},
                {"key": "from_date", "type": "date", "label": "From Date", "description": "Start date (YYYY-MM-DD)", "required": True},
                {"key": "to_date", "type": "date", "label": "To Date", "description": "End date (YYYY-MM-DD)", "required": True}
            ],
            "response_mapping": {
                "queue_id": "$.queue_id",
                "total_calls": "$.total_calls",
                "answered_calls": "$.answered_calls",
                "abandoned_calls": "$.abandoned_calls",
                "average_handle_time": "$.average_handle_time",
                "average_wait_time": "$.average_wait_time"
            }
        },
        {
            "id": "queue_agents_metrics",
            "category": "Analytics",
            "name": "Queue Agent Performance Metrics",
            "description": "Agent performance metrics within a specific queue",
            "method": "GET",
            "path": "/v2/contact_center/analytics/historical/queues/{{queue_id}}/agents/metrics",
            "query_params": [
                {"key": "from", "value": "{{from_date}}", "required": True},
                {"key": "to", "value": "{{to_date}}", "required": True}
            ],
            "variables": [
                {"key": "queue_id", "type": "text", "label": "Queue ID", "description": "The queue ID", "required": True},
                {"key": "from_date", "type": "date", "label": "From Date", "description": "Start date (YYYY-MM-DD)", "required": True},
                {"key": "to_date", "type": "date", "label": "To Date", "description": "End date (YYYY-MM-DD)", "required": True}
            ],
            "response_mapping": {
                "queue_id": "$.queue_id",
                "agents": "$.agents",
                "total_agents": "$.total_agents"
            }
        },
        {
            "id": "queue_summary",
            "category": "Analytics",
            "name": "Queue Summary Metrics",
            "description": "Summary metrics across all queues",
            "method": "GET",
            "path": "/v2/contact_center/analytics/historical/queues/metrics",
            "query_params": [
                {"key": "from", "value": "{{from_date}}", "required": True},
                {"key": "to", "value": "{{to_date}}", "required": True}
            ],
            "variables": [
                {"key": "from_date", "type": "date", "label": "From Date", "description": "Start date (YYYY-MM-DD)", "required": True},
                {"key": "to_date", "type": "date", "label": "To Date", "description": "End date (YYYY-MM-DD)", "required": True}
            ],
            "response_mapping": {
                "total_calls": "$.total_calls",
                "answered_calls": "$.answered_calls",
                "abandoned_calls": "$.abandoned_calls",
                "average_handle_time": "$.average_handle_time",
                "average_wait_time": "$.average_wait_time",
                "service_level": "$.service_level"
            }
        },
        {
            "id": "agent_activity",
            "category": "Analytics",
            "name": "Agent Activity Report",
            "description": "Agent activity report across all agents",
            "method": "GET",
            "path": "/v2/contact_center/analytics/historical/agents/activity",
            "query_params": [
                {"key": "from", "value": "{{from_date}}", "required": True},
                {"key": "to", "value": "{{to_date}}", "required": True}
            ],
            "variables": [
                {"key": "from_date", "type": "date", "label": "From Date", "description": "Start date (YYYY-MM-DD)", "required": True},
                {"key": "to_date", "type": "date", "label": "To Date", "description": "End date (YYYY-MM-DD)", "required": True}
            ],
            "response_mapping": {
                "agents": "$.agents",
                "total_agents": "$.total_agents",
                "total_calls_handled": "$.total_calls_handled",
                "total_talk_time": "$.total_talk_time"
            }
        }
    ]
}


def seed_zoom_cc_integration(db_session):
    """
    Create or update the Zoom Contact Center integration type.
    
    Call this during database initialization or via admin command.
    """
    existing = db_session.query(IntegrationType).filter_by(slug="zoom-contact-center").first()
    
    if existing:
        existing.name = ZOOM_CC_INTEGRATION["name"]
        existing.description = ZOOM_CC_INTEGRATION["description"]
        existing.logo_url = ZOOM_CC_INTEGRATION["logo_url"]
        existing.provider = ZOOM_CC_INTEGRATION["provider"]
        existing.auth_type = ZOOM_CC_INTEGRATION["auth_type"]
        existing.documentation_url = ZOOM_CC_INTEGRATION["documentation_url"]
        existing.set_auth_config(ZOOM_CC_INTEGRATION["auth_config"])
        existing.set_required_fields(ZOOM_CC_INTEGRATION["required_fields"])
        existing.set_endpoints(ZOOM_CC_INTEGRATION["endpoints"])
        print(f"Updated Zoom Contact Center integration type: {existing.id}")
        db_session.commit()
        return existing
    else:
        integration = IntegrationType(
            slug=ZOOM_CC_INTEGRATION["slug"],
            name=ZOOM_CC_INTEGRATION["name"],
            description=ZOOM_CC_INTEGRATION["description"],
            logo_url=ZOOM_CC_INTEGRATION["logo_url"],
            provider=ZOOM_CC_INTEGRATION["provider"],
            auth_type=ZOOM_CC_INTEGRATION["auth_type"],
            documentation_url=ZOOM_CC_INTEGRATION["documentation_url"],
            is_enabled=True
        )
        integration.set_auth_config(ZOOM_CC_INTEGRATION["auth_config"])
        integration.set_required_fields(ZOOM_CC_INTEGRATION["required_fields"])
        integration.set_endpoints(ZOOM_CC_INTEGRATION["endpoints"])
        
        db_session.add(integration)
        db_session.commit()
        print(f"Created Zoom Contact Center integration type: {integration.id}")
        return integration
