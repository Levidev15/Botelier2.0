import json
from botelier.models.integration import IntegrationType


GUESTCENTRIC_INTEGRATION = {
    "slug": "guestcentric-crs",
    "name": "GuestCentric CRS",
    "description": "Connect to GuestCentric Central Reservation System for hotel search, availability, reservations, and guest management.",
    "logo_url": "/integrations/guestcentric-logo.png",
    "provider": "guestcentric",
    "auth_type": "basic_or_jwt",
    "documentation_url": "https://crs-api.guestcentric.net/documentation/developer.html",

    "auth_config": {
        "base_url": "https://crs-api.guestcentric.net/v1.0",
        "auth_methods": ["basic_auth", "jwt"],
        "jwt_login_endpoint": "/authentication/login",
        "jwt_refresh_endpoint": "/authentication/refresh",
        "jwt_check_endpoint": "/authentication/check_token",
        "jwt_max_lifetime_hours": 3,
        "basic_auth_query_params": ["apikey", "hotelId"]
    },

    "required_fields": [
        {
            "key": "auth_method",
            "label": "Authentication Method",
            "type": "select",
            "options": ["basic_auth", "jwt"],
            "description": "Choose Basic Auth for simpler setup or JWT for token-based auth",
            "required": True
        },
        {
            "key": "username",
            "label": "Username",
            "type": "text",
            "placeholder": "Your GuestCentric username",
            "required": True
        },
        {
            "key": "password",
            "label": "Password",
            "type": "password",
            "placeholder": "Your GuestCentric password",
            "required": True
        },
        {
            "key": "apikey",
            "label": "API Key",
            "type": "text",
            "placeholder": "Your API key",
            "description": "API key provided by GuestCentric integrations team",
            "required": True
        },
        {
            "key": "hotelId",
            "label": "Hotel ID (optional)",
            "type": "text",
            "placeholder": "Hotel ID",
            "description": "Hotel ID provided by GuestCentric. Can also be set per-assistant in API request configuration.",
            "required": False
        }
    ],

    "endpoints": [
        {
            "id": "search_locations",
            "category": "Search",
            "name": "Search Locations",
            "description": "Search for available locations (countries, cities, hotels)",
            "method": "GET",
            "path": "/search",
            "query_params": [
                {"key": "text", "value": "{{text}}", "required": True}
            ],
            "variables": [
                {"key": "text", "type": "text", "label": "Search Text", "description": "Search query (minimum 3 characters)", "required": True}
            ],
            "response_mapping": {
                "results": "$.results",
                "count": "$.count"
            }
        },
        {
            "id": "list_hotels",
            "category": "Hotels",
            "name": "List Hotels",
            "description": "List all hotels associated with the account",
            "method": "GET",
            "path": "/hotels",
            "query_params": [
                {"key": "language", "value": "{{language}}", "required": False},
                {"key": "currency", "value": "{{currency}}", "required": False},
                {"key": "hotels", "value": "{{hotels}}", "required": False},
                {"key": "sap_code", "value": "{{sap_code}}", "required": False}
            ],
            "variables": [
                {"key": "language", "type": "text", "label": "Language", "description": "Response language code"},
                {"key": "currency", "type": "text", "label": "Currency", "description": "Currency code for pricing"},
                {"key": "hotels", "type": "text", "label": "Hotel IDs", "description": "JSON array of hotel IDs to filter"},
                {"key": "sap_code", "type": "text", "label": "SAP Code", "description": "SAP code filter"}
            ],
            "response_mapping": {
                "hotels": "$.hotels",
                "count": "$.count"
            }
        },
        {
            "id": "search_hotels",
            "category": "Hotels",
            "name": "Search Hotels",
            "description": "Search hotels by availability criteria",
            "method": "GET",
            "path": "/hotels/search",
            "query_params": [
                {"key": "checkin", "value": "{{checkin}}", "required": True},
                {"key": "checkout", "value": "{{checkout}}", "required": True},
                {"key": "adults", "value": "{{adults}}", "required": True},
                {"key": "children", "value": "{{children}}", "required": False},
                {"key": "city", "value": "{{city}}", "required": False},
                {"key": "country", "value": "{{country}}", "required": False},
                {"key": "hotel_name", "value": "{{hotel_name}}", "required": False},
                {"key": "language", "value": "{{language}}", "required": False},
                {"key": "currency", "value": "{{currency}}", "required": False},
                {"key": "minimum_price", "value": "{{minimum_price}}", "required": False},
                {"key": "maximum_price", "value": "{{maximum_price}}", "required": False},
                {"key": "price_type", "value": "{{price_type}}", "required": False}
            ],
            "variables": [
                {"key": "checkin", "type": "date", "label": "Check-in Date", "description": "Check-in date (YYYY-MM-DD)", "required": True},
                {"key": "checkout", "type": "date", "label": "Check-out Date", "description": "Check-out date (YYYY-MM-DD)", "required": True},
                {"key": "adults", "type": "number", "label": "Adults", "description": "Number of adults", "required": True},
                {"key": "children", "type": "number", "label": "Children", "description": "Number of children"},
                {"key": "city", "type": "text", "label": "City", "description": "Filter by city"},
                {"key": "country", "type": "text", "label": "Country", "description": "Filter by country"},
                {"key": "hotel_name", "type": "text", "label": "Hotel Name", "description": "Filter by hotel name"},
                {"key": "language", "type": "text", "label": "Language", "description": "Response language code"},
                {"key": "currency", "type": "text", "label": "Currency", "description": "Currency code for pricing"},
                {"key": "minimum_price", "type": "number", "label": "Minimum Price", "description": "Minimum price filter"},
                {"key": "maximum_price", "type": "number", "label": "Maximum Price", "description": "Maximum price filter"},
                {"key": "price_type", "type": "text", "label": "Price Type", "description": "Price type for filtering"}
            ],
            "response_mapping": {
                "hotels": "$.hotels",
                "count": "$.count"
            }
        },
        {
            "id": "hotel_rooms",
            "category": "Hotels",
            "name": "Hotel Rooms",
            "description": "Get rooms and pricing for a specific hotel",
            "method": "GET",
            "path": "/hotels/{{hotel_id}}/rooms",
            "variables": [
                {"key": "hotel_id", "type": "text", "label": "Hotel ID", "description": "The hotel ID", "required": True}
            ],
            "response_mapping": {
                "rooms": "$.rooms"
            }
        },
        {
            "id": "hotel_cancellation_policies",
            "category": "Hotels",
            "name": "Hotel Cancellation Policies",
            "description": "Get cancellation policies for a hotel",
            "method": "GET",
            "path": "/hotels/{{hotel_id}}/cancellation-policies",
            "variables": [
                {"key": "hotel_id", "type": "text", "label": "Hotel ID", "description": "The hotel ID", "required": True}
            ],
            "response_mapping": {
                "policies": "$.policies"
            }
        },
        {
            "id": "hotel_guarantee_policies",
            "category": "Hotels",
            "name": "Hotel Guarantee Policies",
            "description": "Get guarantee policies for a hotel",
            "method": "GET",
            "path": "/hotels/{{hotel_id}}/guarantee-policies",
            "variables": [
                {"key": "hotel_id", "type": "text", "label": "Hotel ID", "description": "The hotel ID", "required": True}
            ],
            "response_mapping": {
                "policies": "$.policies"
            }
        },
        {
            "id": "hotel_currencies",
            "category": "Hotels",
            "name": "Hotel Currencies",
            "description": "Get all available hotel currencies",
            "method": "GET",
            "path": "/hotels/currencies",
            "variables": [],
            "response_mapping": {
                "currencies": "$.currencies"
            }
        },
        {
            "id": "hotel_addons",
            "category": "Hotels",
            "name": "Hotel Addons",
            "description": "Get available addons for a hotel",
            "method": "GET",
            "path": "/hotels/{{hotel_id}}/addons",
            "variables": [
                {"key": "hotel_id", "type": "text", "label": "Hotel ID", "description": "The hotel ID", "required": True}
            ],
            "response_mapping": {
                "addons": "$.addons"
            }
        },
        {
            "id": "book_reservation",
            "category": "Reservations",
            "name": "Book Reservation",
            "description": "Create a new reservation",
            "method": "POST",
            "path": "/reservations/book",
            "body_template": {
                "hotel_id": "{{hotel_id}}",
                "checkin": "{{checkin}}",
                "checkout": "{{checkout}}",
                "adults": "{{adults}}",
                "children": "{{children}}",
                "room_id": "{{room_id}}",
                "rate_id": "{{rate_id}}",
                "guest": {
                    "first_name": "{{guest_first_name}}",
                    "last_name": "{{guest_last_name}}",
                    "email": "{{guest_email}}",
                    "phone": "{{guest_phone}}"
                }
            },
            "variables": [
                {"key": "hotel_id", "type": "text", "label": "Hotel ID", "required": True},
                {"key": "checkin", "type": "date", "label": "Check-in Date", "required": True},
                {"key": "checkout", "type": "date", "label": "Check-out Date", "required": True},
                {"key": "adults", "type": "number", "label": "Adults", "default": 1, "required": True},
                {"key": "children", "type": "number", "label": "Children", "default": 0},
                {"key": "room_id", "type": "text", "label": "Room ID", "required": True},
                {"key": "rate_id", "type": "text", "label": "Rate ID", "required": True},
                {"key": "guest_first_name", "type": "text", "label": "Guest First Name", "required": True},
                {"key": "guest_last_name", "type": "text", "label": "Guest Last Name", "required": True},
                {"key": "guest_email", "type": "text", "label": "Guest Email", "required": True},
                {"key": "guest_phone", "type": "text", "label": "Guest Phone"}
            ],
            "response_mapping": {
                "reservation_id": "$.reservation_id",
                "confirmation_number": "$.confirmation_number",
                "status": "$.status"
            }
        },
        {
            "id": "list_reservations",
            "category": "Reservations",
            "name": "List Reservations",
            "description": "List reservations with optional filters",
            "method": "GET",
            "path": "/reservations",
            "query_params": [
                {"key": "hotel_id", "value": "{{hotel_id}}", "required": False},
                {"key": "checkin", "value": "{{checkin}}", "required": False},
                {"key": "checkout", "value": "{{checkout}}", "required": False},
                {"key": "status", "value": "{{status}}", "required": False},
                {"key": "confirmation_number", "value": "{{confirmation_number}}", "required": False},
                {"key": "guest_name", "value": "{{guest_name}}", "required": False}
            ],
            "variables": [
                {"key": "hotel_id", "type": "text", "label": "Hotel ID", "description": "Filter by hotel ID"},
                {"key": "checkin", "type": "date", "label": "Check-in Date", "description": "Filter by check-in date"},
                {"key": "checkout", "type": "date", "label": "Check-out Date", "description": "Filter by check-out date"},
                {"key": "status", "type": "text", "label": "Status", "description": "Filter by reservation status"},
                {"key": "confirmation_number", "type": "text", "label": "Confirmation Number", "description": "Filter by confirmation number"},
                {"key": "guest_name", "type": "text", "label": "Guest Name", "description": "Filter by guest name"}
            ],
            "response_mapping": {
                "reservations": "$.reservations",
                "count": "$.count"
            }
        },
        {
            "id": "view_reservation",
            "category": "Reservations",
            "name": "View Reservation",
            "description": "View a specific reservation's details",
            "method": "GET",
            "path": "/reservations/{{reservation_id}}",
            "variables": [
                {"key": "reservation_id", "type": "text", "label": "Reservation ID", "description": "The reservation ID", "required": True}
            ],
            "response_mapping": {
                "reservation_id": "$.reservation_id",
                "confirmation_number": "$.confirmation_number",
                "status": "$.status",
                "guest_name": "$.guest.name",
                "checkin": "$.checkin",
                "checkout": "$.checkout"
            }
        },
        {
            "id": "update_reservation",
            "category": "Reservations",
            "name": "Update Reservation",
            "description": "Update reservation values",
            "method": "PUT",
            "path": "/reservations/{{reservation_id}}",
            "variables": [
                {"key": "reservation_id", "type": "text", "label": "Reservation ID", "description": "The reservation ID", "required": True}
            ]
        },
        {
            "id": "modify_reservation",
            "category": "Reservations",
            "name": "Modify Reservation",
            "description": "Modify a reservation (dates, room, etc.)",
            "method": "PUT",
            "path": "/reservations/{{reservation_id}}/modify",
            "variables": [
                {"key": "reservation_id", "type": "text", "label": "Reservation ID", "description": "The reservation ID", "required": True}
            ]
        },
        {
            "id": "cancel_reservation",
            "category": "Reservations",
            "name": "Cancel Reservation",
            "description": "Cancel a reservation",
            "method": "POST",
            "path": "/reservations/{{reservation_id}}/cancel",
            "variables": [
                {"key": "reservation_id", "type": "text", "label": "Reservation ID", "description": "The reservation ID", "required": True}
            ],
            "response_mapping": {
                "status": "$.status"
            }
        },
        {
            "id": "resend_email",
            "category": "Reservations",
            "name": "Resend Confirmation Email",
            "description": "Re-send reservation confirmation email",
            "method": "POST",
            "path": "/reservations/{{reservation_id}}/resend-email",
            "variables": [
                {"key": "reservation_id", "type": "text", "label": "Reservation ID", "description": "The reservation ID", "required": True}
            ],
            "response_mapping": {
                "status": "$.status"
            }
        }
    ]
}


def seed_guestcentric_integration(db_session):
    existing = db_session.query(IntegrationType).filter_by(slug="guestcentric-crs").first()

    if existing:
        existing.name = GUESTCENTRIC_INTEGRATION["name"]
        existing.description = GUESTCENTRIC_INTEGRATION["description"]
        existing.logo_url = GUESTCENTRIC_INTEGRATION["logo_url"]
        existing.provider = GUESTCENTRIC_INTEGRATION["provider"]
        existing.auth_type = GUESTCENTRIC_INTEGRATION["auth_type"]
        existing.documentation_url = GUESTCENTRIC_INTEGRATION["documentation_url"]
        existing.set_auth_config(GUESTCENTRIC_INTEGRATION["auth_config"])
        existing.set_required_fields(GUESTCENTRIC_INTEGRATION["required_fields"])
        existing.set_endpoints(GUESTCENTRIC_INTEGRATION["endpoints"])
        print(f"Updated GuestCentric CRS integration type: {existing.id}")
        db_session.commit()
        return existing
    else:
        integration = IntegrationType(
            slug=GUESTCENTRIC_INTEGRATION["slug"],
            name=GUESTCENTRIC_INTEGRATION["name"],
            description=GUESTCENTRIC_INTEGRATION["description"],
            logo_url=GUESTCENTRIC_INTEGRATION["logo_url"],
            provider=GUESTCENTRIC_INTEGRATION["provider"],
            auth_type=GUESTCENTRIC_INTEGRATION["auth_type"],
            documentation_url=GUESTCENTRIC_INTEGRATION["documentation_url"],
            is_enabled=True
        )
        integration.set_auth_config(GUESTCENTRIC_INTEGRATION["auth_config"])
        integration.set_required_fields(GUESTCENTRIC_INTEGRATION["required_fields"])
        integration.set_endpoints(GUESTCENTRIC_INTEGRATION["endpoints"])

        db_session.add(integration)
        db_session.commit()
        print(f"Created GuestCentric CRS integration type: {integration.id}")
        return integration
