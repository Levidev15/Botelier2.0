"""Oracle Opera Cloud OHIP Integration Seed Data.

This seeds the IntegrationType for Oracle Opera Cloud with proper OHIP API
configuration including OAuth settings and pre-built endpoint templates.
"""

import json

from botelier.models.integration import IntegrationType

OPERA_CLOUD_INTEGRATION = {
    "slug": "opera-cloud",
    "name": "Oracle Opera Cloud",
    "description": "Connect to Oracle Hospitality OPERA Cloud for reservation management, guest profiles, and property operations via OHIP APIs.",
    "logo_url": "/integrations/opera-cloud-logo.png",
    "provider": "oracle",
    "auth_type": "oauth2_client_credentials",
    "documentation_url": "https://docs.oracle.com/en/industries/hospitality/integration-platform/ohipu/",
    "auth_config": {
        # OHIP OAuth2 client_credentials flow.
        # Token endpoint: POST {gateway_url}/oauth/v1/tokens
        # Auth: HTTP Basic (client_id:client_secret)
        # Body: grant_type=client_credentials&scope=<scope>
        # x-app-key header: set to the app_key credential when present,
        #                    otherwise falls back to client_id (sandbox behaviour).
        "token_endpoint_path": "/oauth/v1/tokens",
        "grant_type": "client_credentials",
        "scope": "urn:opc:hgbu:ws:__myscopes__",
        "token_header": "Authorization",
        "token_prefix": "Bearer",
    },
    "required_fields": [
        {
            "key": "gateway_url",
            "label": "Gateway URL",
            "type": "url",
            "placeholder": "https://your-environment.hospitality.oraclecloud.com",
            "description": "Your OHIP gateway URL from the Developer Portal Environments tab",
            "required": True,
        },
        {
            "key": "client_id",
            "label": "Client ID",
            "type": "text",
            "placeholder": "Your OAuth Client ID",
            "description": "OAuth Client ID from the Developer Portal. Also used as x-app-key in the sandbox when no separate Application Key is provided.",
            "required": True,
        },
        {
            "key": "client_secret",
            "label": "Client Secret",
            "type": "password",
            "placeholder": "Your OAuth Client Secret",
            "description": "OAuth Client Secret from the Developer Portal",
            "required": True,
        },
        {
            "key": "enterprise_id",
            "label": "Enterprise ID",
            "type": "text",
            "placeholder": "e.g. OCR4ENT",
            "description": "Your Oracle Hospitality Enterprise ID",
            "required": True,
        },
        {
            "key": "hotel_id",
            "label": "Hotel ID (Property Code)",
            "type": "text",
            "placeholder": "e.g. OHIPSB02",
            "description": "The property/hotel ID in OPERA Cloud. Sent as x-hotelid header on all OHIP API calls.",
            "required": True,
        },
        {
            "key": "chain_code",
            "label": "Chain Code",
            "type": "text",
            "placeholder": "e.g. OHIPLAB",
            "description": "Your Oracle chain code. Sent as x-chainid header on OHIP API calls that require it. Optional for sandbox.",
            "required": False,
        },
        {
            "key": "app_key",
            "label": "Application Key (optional)",
            "type": "password",
            "placeholder": "Leave blank to use Client ID (sandbox default)",
            "description": "x-app-key value for production environments where the app key differs from the Client ID. Leave blank for the OHIP sandbox.",
            "required": False,
        },
    ],
    "endpoints": [
        {
            "id": "get_reservation",
            "canonical_entity": "reservation",
            "capability": "lookup_reservation",
            "capability_params": {"confirmation_number": "confirmation_number"},
            "category": "Reservations",
            "name": "Get Reservation by Confirmation Number",
            "description": "Retrieve reservation details by confirmation number",
            "method": "GET",
            "path": "/rsv/v1/hotels/{{hotel_id}}/reservations",
            "query_params": [
                {"key": "confirmationNumbers", "value": "{{confirmation_number}}", "required": True}
            ],
            "variables": [
                {
                    "key": "confirmation_number",
                    "type": "text",
                    "label": "Confirmation Number",
                    "description": "The reservation confirmation number",
                }
            ],
            "response_mapping": {
                "reservation_id": "$.reservations.reservationInfo[0].reservationIdList[0].id",
                "guest_name": "$.reservations.reservationInfo[0].guestName.givenName",
                "arrival_date": "$.reservations.reservationInfo[0].arrivalDate",
                "departure_date": "$.reservations.reservationInfo[0].departureDate",
                "room_type": "$.reservations.reservationInfo[0].roomType",
                "status": "$.reservations.reservationInfo[0].reservationStatus",
            },
            "response_mapping_labels": {
                "reservation_id": "System reservation identifier",
                "guest_name": "Guest given name",
                "arrival_date": "Check-in date (YYYY-MM-DD)",
                "departure_date": "Check-out date (YYYY-MM-DD)",
                "room_type": "Room type code",
                "status": "Reservation status (e.g. RESERVED, INHOUSE)",
            },
        },
        {
            "id": "search_reservations",
            "canonical_entity": "reservation",
            "category": "Reservations",
            "name": "Search Reservations",
            "description": "Search for reservations by various criteria",
            "method": "GET",
            "path": "/rsv/v1/hotels/{{hotel_id}}/reservations",
            "query_params": [
                {"key": "givenName", "value": "{{guest_first_name}}", "required": False},
                {"key": "surname", "value": "{{guest_last_name}}", "required": False},
                {"key": "arrivalStartDate", "value": "{{arrival_date}}", "required": False},
                {"key": "arrivalEndDate", "value": "{{arrival_end_date}}", "required": False},
            ],
            "variables": [
                {
                    "key": "guest_first_name",
                    "type": "text",
                    "label": "Guest First Name",
                    "description": "Guest's first name",
                },
                {
                    "key": "guest_last_name",
                    "type": "text",
                    "label": "Guest Last Name",
                    "description": "Guest's last name",
                },
                {
                    "key": "arrival_date",
                    "type": "date",
                    "label": "Arrival Date",
                    "description": "Start of arrival date range (YYYY-MM-DD)",
                },
                {
                    "key": "arrival_end_date",
                    "type": "date",
                    "label": "Arrival End Date",
                    "description": "End of arrival date range (YYYY-MM-DD)",
                },
            ],
            "response_mapping": {
                "reservations": "$.reservations.reservationInfo",
                "count": "$.reservations.count",
            },
            "response_mapping_labels": {
                "reservations": "Array of matching reservation objects",
                "count": "Total number of results returned",
            },
        },
        {
            "id": "create_reservation",
            "capability": "book_reservation",
            "capability_params": {
                "guest_first_name": "guest_first_name",
                "guest_last_name": "guest_last_name",
                "check_in_date": "check_in_date",
                "check_out_date": "check_out_date",
                "room_type": "room_type",
                "rate_code": "rate_code",
                "guest_count": "guest_count",
                "children": "child_count",
            },
            "category": "Reservations",
            "name": "Create Reservation",
            "description": "Create a new reservation in OPERA Cloud",
            "method": "POST",
            "path": "/rsv/v1/hotels/{{hotel_id}}/reservations",
            "body_template": {
                "reservations": {
                    "reservation": [
                        {
                            "hotelId": "{{hotel_id}}",
                            "reservationGuests": {
                                "profileInfo": [
                                    {
                                        "profile": {
                                            "profileType": "Guest",
                                            "customer": {
                                                "personName": [
                                                    {
                                                        "givenName": "{{guest_first_name}}",
                                                        "surname": "{{guest_last_name}}",
                                                    }
                                                ]
                                            },
                                        }
                                    }
                                ]
                            },
                            "roomStay": {
                                "arrivalDate": "{{check_in_date}}",
                                "departureDate": "{{check_out_date}}",
                                "roomTypes": [{"roomTypeCode": "{{room_type}}"}],
                                "ratePlanCodes": [{"ratePlanCode": "{{rate_code}}"}],
                                "guestCounts": {
                                    "adults": "{{guest_count}}",
                                    "children": "{{child_count}}",
                                },
                            },
                        }
                    ]
                }
            },
            "variables": [
                {
                    "key": "guest_first_name",
                    "type": "text",
                    "label": "Guest First Name",
                    "required": True,
                },
                {
                    "key": "guest_last_name",
                    "type": "text",
                    "label": "Guest Last Name",
                    "required": True,
                },
                {"key": "check_in_date", "type": "date", "label": "Arrival Date", "required": True},
                {
                    "key": "check_out_date",
                    "type": "date",
                    "label": "Departure Date",
                    "required": True,
                },
                {"key": "room_type", "type": "text", "label": "Room Type Code", "required": True},
                {"key": "rate_code", "type": "text", "label": "Rate Plan Code", "required": True},
                {"key": "guest_count", "type": "number", "label": "Number of Adults", "default": 1},
                {
                    "key": "child_count",
                    "type": "number",
                    "label": "Number of Children",
                    "default": 0,
                },
            ],
            "response_mapping": {
                "confirmation_number": "$.reservationId.id",
                "booking_url": "$.links[0].href",
            },
            "response_mapping_labels": {
                "confirmation_number": "Opera reservation ID / confirmation number",
                "booking_url": "HATEOAS self-link for the new reservation",
            },
        },
        {
            # Task #339 — combined booking + card capture. Deliberately NOT tagged
            # with a `capability` so it never competes with `create_reservation`
            # for `book_reservation` resolution (that would fail closed as
            # ambiguous). `supports_card_capture` is the marker the capability
            # resolver uses to detect a PMS-native payment path for the property,
            # and the combined-submit endpoint calls this endpoint id directly.
            # Card values (number/expiry/cvv) are forwarded in-memory to OPERA's
            # PCI-certified gateway and NEVER written to a Botelier log or DB row.
            "id": "create_reservation_with_payment",
            "supports_card_capture": True,
            "category": "Reservations",
            "name": "Create Reservation with Payment",
            "description": (
                "Create a reservation AND attach the guest's credit card in one "
                "call so OPERA's own payment gateway can charge the deposit. Card "
                "details are forwarded to OPERA and are never stored by Botelier."
            ),
            "method": "POST",
            "path": "/rsv/v1/hotels/{{hotel_id}}/reservations",
            "body_template": {
                "reservations": {
                    "reservation": [
                        {
                            "hotelId": "{{hotel_id}}",
                            "reservationGuests": {
                                "profileInfo": [
                                    {
                                        "profile": {
                                            "profileType": "Guest",
                                            "customer": {
                                                "personName": [
                                                    {
                                                        "givenName": "{{guest_first_name}}",
                                                        "surname": "{{guest_last_name}}",
                                                    }
                                                ]
                                            },
                                        }
                                    }
                                ]
                            },
                            "roomStay": {
                                "arrivalDate": "{{check_in_date}}",
                                "departureDate": "{{check_out_date}}",
                                "roomTypes": [{"roomTypeCode": "{{room_type}}"}],
                                "ratePlanCodes": [{"ratePlanCode": "{{rate_code}}"}],
                                "guestCounts": {
                                    "adults": "{{guest_count}}",
                                    "children": "{{child_count}}",
                                },
                                "guarantee": {"guaranteeCode": "CC"},
                            },
                            "reservationPaymentMethods": [
                                {
                                    "paymentMethod": "CC",
                                    "folioView": "Room",
                                    "paymentCard": {
                                        "cardHolderName": "{{card_holder}}",
                                        "cardNumber": "{{card_number}}",
                                        "expirationDate": "{{card_expiry}}",
                                        "cardSecurityCode": "{{card_cvv}}",
                                    },
                                }
                            ],
                        }
                    ]
                }
            },
            "variables": [
                {"key": "guest_first_name", "type": "text", "label": "Guest First Name", "required": True},
                {"key": "guest_last_name", "type": "text", "label": "Guest Last Name", "required": True},
                {"key": "check_in_date", "type": "date", "label": "Arrival Date", "required": True},
                {"key": "check_out_date", "type": "date", "label": "Departure Date", "required": True},
                {"key": "room_type", "type": "text", "label": "Room Type Code", "required": True},
                {"key": "rate_code", "type": "text", "label": "Rate Plan Code", "required": True},
                {"key": "guest_count", "type": "number", "label": "Number of Adults", "default": 1},
                {"key": "child_count", "type": "number", "label": "Number of Children", "default": 0},
                {"key": "card_holder", "type": "text", "label": "Card Holder Name", "required": True},
                {"key": "card_number", "type": "text", "label": "Card Number", "required": True},
                {"key": "card_expiry", "type": "text", "label": "Card Expiry (MM/YY)", "required": True},
                {"key": "card_cvv", "type": "text", "label": "Card CVV", "required": True},
            ],
            "response_mapping": {
                "confirmation_number": "$.reservationId.id",
                "booking_url": "$.links[0].href",
            },
            "response_mapping_labels": {
                "confirmation_number": "Opera reservation ID / confirmation number",
                "booking_url": "HATEOAS self-link for the new reservation",
            },
        },
        {
            "id": "get_guest_profile",
            "canonical_entity": "guest",
            "category": "Profiles",
            "name": "Get Guest Profile",
            "description": "Retrieve a guest profile by profile ID",
            "method": "GET",
            "path": "/crm/v1/profiles/{{profile_id}}",
            "variables": [
                {
                    "key": "profile_id",
                    "type": "text",
                    "label": "Profile ID",
                    "description": "The guest profile ID",
                    "required": True,
                }
            ],
            "response_mapping": {
                "profile_id": "$.profileDetails.profileId.id",
                "first_name": "$.profileDetails.customer.personName[0].givenName",
                "last_name": "$.profileDetails.customer.personName[0].surname",
                "email": "$.profileDetails.emails[0].email",
                "phone": "$.profileDetails.phones[0].phoneNumber",
            },
            "response_mapping_labels": {
                "profile_id": "Guest profile system identifier",
                "first_name": "Guest given (first) name",
                "last_name": "Guest family (last) name",
                "email": "Primary email address",
                "phone": "Primary phone number",
            },
        },
        {
            "id": "search_profiles",
            "canonical_entity": "guest",
            "category": "Profiles",
            "name": "Search Guest Profiles",
            "description": "Search for guest profiles by name, email, or phone",
            "method": "GET",
            "path": "/crm/v1/profiles",
            "query_params": [
                {"key": "givenName", "value": "{{first_name}}", "required": False},
                {"key": "profileName", "value": "{{last_name}}", "required": False},
                {"key": "email", "value": "{{email}}", "required": False},
                {"key": "phone", "value": "{{phone}}", "required": False},
            ],
            "variables": [
                {"key": "first_name", "type": "text", "label": "First Name"},
                {"key": "last_name", "type": "text", "label": "Last Name"},
                {"key": "email", "type": "text", "label": "Email Address"},
                {"key": "phone", "type": "text", "label": "Phone Number"},
            ],
            "response_mapping": {
                "profiles": "$.profileSummaries.profileInfo",
                "count": "$.profileSummaries.count",
            },
            "response_mapping_labels": {
                "profiles": "Array of matching guest profile objects",
                "count": "Total number of profiles found",
            },
        },
        {
            "id": "check_availability",
            "canonical_entity": "availability",
            "capability": "search_availability",
            "capability_params": {
                "check_in_date": "check_in_date",
                "check_out_date": "check_out_date",
                "guest_count": "guest_count",
                "children": "children",
            },
            "category": "Availability",
            "name": "Check Room Availability",
            "description": "Check room availability for given dates",
            "method": "GET",
            "path": "/par/v1/hotels/{{hotel_id}}/availability",
            "query_params": [
                {"key": "roomStayStartDate", "value": "{{check_in_date}}", "required": True},
                {"key": "roomStayEndDate", "value": "{{check_out_date}}", "required": True},
                {"key": "adults", "value": "{{guest_count}}", "required": True},
                {"key": "children", "value": "{{children}}", "required": False},
                {"key": "roomType", "value": "{{room_type}}", "required": False},
            ],
            "variables": [
                {"key": "check_in_date", "type": "date", "label": "Check-in Date", "required": True},
                {"key": "check_out_date", "type": "date", "label": "Check-out Date", "required": True},
                {"key": "guest_count", "type": "number", "label": "Number of Adults", "default": 1},
                {"key": "children", "type": "number", "label": "Number of Children", "default": 0},
                {"key": "room_type", "type": "text", "label": "Room Type (optional)"},
            ],
            "response_mapping": {
                "available_rooms": "$.hotelAvailability[*].roomStays[*].roomRates[*].roomType",
                "rates": "$.hotelAvailability[*].roomStays[*].roomRates[*].ratePlanCode",
            },
            "response_mapping_labels": {
                "available_rooms": "List of available room types for the dates",
                "rates": "List of applicable rate plans",
            },
        },
        {
            "id": "get_room_types",
            "canonical_entity": "room",
            "category": "Configuration",
            "name": "Get Room Types",
            "description": "Get list of all room types configured in the property",
            "method": "GET",
            "path": "/lov/v1/listOfValues/hotels/{{hotel_id}}/roomTypes",
            "variables": [],
            "response_mapping": {"room_types": "$.listOfValues.items"},
            "response_mapping_labels": {
                "room_types": "All configured room types at the property",
            },
        },
        {
            "id": "get_rate_plans",
            "canonical_entity": "rate_plan",
            "category": "Configuration",
            "name": "Get Rate Plans",
            "description": "Get list of all rate plans configured in the property",
            "method": "GET",
            "path": "/rtp/v1/hotels/{{hotel_id}}/ratePlans",
            "variables": [],
            "response_mapping": {"rate_plans": "$.ratePlans"},
            "response_mapping_labels": {
                "rate_plans": "All configured rate plans at the property",
            },
        },
        {
            "id": "get_in_house_guests",
            "canonical_entity": "reservation",
            "category": "Front Desk",
            "name": "Get In-House Guests",
            "description": "Get list of currently checked-in guests",
            "method": "GET",
            "path": "/rsv/v1/hotels/{{hotel_id}}/reservations",
            "query_params": [{"key": "reservationStatuses", "value": "INHOUSE", "required": True}],
            "variables": [],
            "response_mapping": {
                "guests": "$.reservations.reservationInfo",
                "count": "$.reservations.count",
            },
            "response_mapping_labels": {
                "guests": "List of currently checked-in guest records",
                "count": "Total number of in-house guests",
            },
        },
        {
            "id": "get_arrivals",
            "canonical_entity": "reservation",
            "category": "Front Desk",
            "name": "Get Today's Arrivals",
            "description": "Get list of guests arriving today",
            "method": "GET",
            "path": "/rsv/v1/hotels/{{hotel_id}}/reservations",
            "query_params": [
                {"key": "reservationStatuses", "value": "RESERVED", "required": True},
                {"key": "arrivalStartDate", "value": "{{date}}", "required": True},
                {"key": "arrivalEndDate", "value": "{{date}}", "required": True},
            ],
            "variables": [
                {"key": "date", "type": "date", "label": "Arrival Date", "default": "today"}
            ],
            "response_mapping": {
                "arrivals": "$.reservations.reservationInfo",
                "count": "$.reservations.count",
            },
            "response_mapping_labels": {
                "arrivals": "List of guests expected to arrive on the given date",
                "count": "Total number of expected arrivals",
            },
        },
    ],
}


def seed_opera_integration(db_session):
    """Create or update the Oracle Opera Cloud integration type.

    Call this during database initialization or via admin command.
    """
    existing = db_session.query(IntegrationType).filter_by(slug="opera-cloud").first()

    if existing:
        existing.name = OPERA_CLOUD_INTEGRATION["name"]
        existing.description = OPERA_CLOUD_INTEGRATION["description"]
        existing.logo_url = OPERA_CLOUD_INTEGRATION["logo_url"]
        existing.provider = OPERA_CLOUD_INTEGRATION["provider"]
        existing.auth_type = OPERA_CLOUD_INTEGRATION["auth_type"]
        existing.documentation_url = OPERA_CLOUD_INTEGRATION["documentation_url"]
        existing.set_auth_config(OPERA_CLOUD_INTEGRATION["auth_config"])
        existing.set_required_fields(OPERA_CLOUD_INTEGRATION["required_fields"])
        existing.set_endpoints(OPERA_CLOUD_INTEGRATION["endpoints"])
        print(f"Updated Opera Cloud integration type: {existing.id}")
        db_session.commit()
        return existing
    else:
        integration = IntegrationType(
            slug=OPERA_CLOUD_INTEGRATION["slug"],
            name=OPERA_CLOUD_INTEGRATION["name"],
            description=OPERA_CLOUD_INTEGRATION["description"],
            logo_url=OPERA_CLOUD_INTEGRATION["logo_url"],
            provider=OPERA_CLOUD_INTEGRATION["provider"],
            auth_type=OPERA_CLOUD_INTEGRATION["auth_type"],
            documentation_url=OPERA_CLOUD_INTEGRATION["documentation_url"],
            is_enabled=True,
        )
        integration.set_auth_config(OPERA_CLOUD_INTEGRATION["auth_config"])
        integration.set_required_fields(OPERA_CLOUD_INTEGRATION["required_fields"])
        integration.set_endpoints(OPERA_CLOUD_INTEGRATION["endpoints"])

        db_session.add(integration)
        db_session.commit()
        print(f"Created Opera Cloud integration type: {integration.id}")
        return integration
