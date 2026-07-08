---
id: adding-a-new-integration
title: Adding a New Integration
sidebar_label: Adding a New Integration
---

# Adding a New Integration

This is the single authoritative, start-to-finish guide for adding a new **pre-built integration** to Botelier — the kind that shows up in **Integrations → Connect Integration**, gets encrypted per-account credentials, and surfaces certified endpoints in the **API Request** flow node with auto-populated response mappings.

It is written so a coder *or* an AI coding agent can go from nothing to a fully working, selectable-in-a-flow integration without reading any other file first. It uses the two integrations that already ship with Botelier as concrete, working references:

- **Oracle Opera Cloud (OHIP)** — `botelier/backend/botelier/seeds/opera_integration.py` — `auth_type: "oauth2_client_credentials"`
- **GuestCentric CRS** — `botelier/backend/botelier/seeds/guestcentric_integration.py` — `auth_type: "basic_or_jwt"`

Read those two files side by side with this guide. Every claim below is grounded in what those files (and the runtime code that executes them) actually do — not an aspirational shape.

:::info Scope
This guide is documentation only. It does not change seed data, runtime behavior, or flow-editor code. If something you need isn't supported by the current runtime (e.g. a third auth type), that's a code change to `services/integration_client.py` first — this guide only tells you how to work within what exists today.
:::

## Mental model

| Concept | Where it lives | Purpose |
|---|---|---|
| `IntegrationType` | `botelier/backend/botelier/models/integration.py`, one row per integration **kind** (Opera, GuestCentric, …) | The platform-level catalog entry: auth shape, credential form fields, and the certified endpoint catalog. Seeded at startup, shared by every account. |
| `AccountIntegration` | Same file, one row per **account's connection** to an `IntegrationType` | Encrypted credentials, access/refresh tokens, connection status. Created when a user fills in the Connect form. |
| `IntegrationClient` | `botelier/backend/botelier/services/integration_client.py` | Runtime engine: resolves credentials, refreshes tokens, builds the URL/headers/body for a given endpoint, executes the HTTP call, and extracts response variables. |
| API Request node | `botelier/frontend/components/flow-editor/inspectors/APIRequestNodePanel.tsx` | Where a flow author picks a connected integration + one of its endpoints, and maps its response into flow variables. |

The lifecycle: **seed defines the shape → account connects (fills `required_fields`, some conditionally shown) → `IntegrationClient` handles auth/refresh/request-building → the endpoint's `response_mapping` surfaces as suggested flow variables → the flow's AI logic uses those variables.**

`IntegrationType.auth_type` currently supports exactly two values, and `IntegrationClient` branches on them explicitly:

| `auth_type` | Token model | Credentials come from | Worked example |
|---|---|---|---|
| `oauth2_client_credentials` | OAuth2 client-credentials grant, access token refreshed automatically before expiry | `client_id` / `client_secret` (HTTP Basic on the token endpoint) + a user-supplied `gateway_url` | Oracle Opera OHIP |
| `basic_or_jwt` | Either static HTTP Basic (no token) **or** a JWT obtained via login/refresh endpoints, chosen per-account via a `select` field | `username` / `password` (+ provider API key/hotel params) | GuestCentric CRS |

There is no generic "API key" or "no-auth" `auth_type` today — model one of the two above, or extend `integration_client.py` first (out of scope for this guide).

## Step 1 — Write the seed module

### File and function contract

Create `botelier/backend/botelier/seeds/<name>_integration.py`. Every seed module must expose:

```python
def seed_<name>_integration(db: Session) -> None:
    ...
```

The function must be **idempotent** — safe to run on every app startup. Both real seeds use the same pattern: query by `slug`, update the row in place if it exists, otherwise construct and insert one. Neither uses a Postgres `ON CONFLICT` upsert — follow the pattern below, not a raw `INSERT ... ON CONFLICT`:

```python
def seed_<name>_integration(db_session):
    existing = db_session.query(IntegrationType).filter_by(slug="<slug>").first()

    if existing:
        existing.name = MY_INTEGRATION["name"]
        existing.description = MY_INTEGRATION["description"]
        existing.logo_url = MY_INTEGRATION["logo_url"]
        existing.provider = MY_INTEGRATION["provider"]
        existing.auth_type = MY_INTEGRATION["auth_type"]
        existing.documentation_url = MY_INTEGRATION["documentation_url"]
        existing.set_auth_config(MY_INTEGRATION["auth_config"])
        existing.set_required_fields(MY_INTEGRATION["required_fields"])
        existing.set_endpoints(MY_INTEGRATION["endpoints"])
        db_session.commit()
        return existing
    else:
        integration = IntegrationType(
            slug=MY_INTEGRATION["slug"],
            name=MY_INTEGRATION["name"],
            description=MY_INTEGRATION["description"],
            logo_url=MY_INTEGRATION["logo_url"],
            provider=MY_INTEGRATION["provider"],
            auth_type=MY_INTEGRATION["auth_type"],
            documentation_url=MY_INTEGRATION["documentation_url"],
            is_enabled=True,
        )
        integration.set_auth_config(MY_INTEGRATION["auth_config"])
        integration.set_required_fields(MY_INTEGRATION["required_fields"])
        integration.set_endpoints(MY_INTEGRATION["endpoints"])
        db_session.add(integration)
        db_session.commit()
        return integration
```

`set_auth_config` / `set_required_fields` / `set_endpoints` (defined on the `IntegrationType` model) JSON-serialize into the `auth_config`, `required_fields`, and `endpoints_config` `Text` columns respectively. Never write raw JSON strings to those columns yourself — always go through these setters (and read back through `get_auth_config()` / `get_required_fields()` / `get_endpoints()`).

### Top-level `IntegrationType` fields

| Field | Notes |
|---|---|
| `slug` | Stable, lowercase, hyphenated identifier (e.g. `"guestcentric-crs"`). Used everywhere downstream — flow templates hardcode it as `integrationSlug`. Never change it after any account has connected. |
| `name` | Display name shown in the Connect Integration list and the API Request node's integration dropdown. |
| `description` | One-line description shown in the Connect Integration list. |
| `logo_url` | Path to a logo asset under the frontend's public integrations folder. |
| `provider` | Free-text vendor identifier (e.g. `"oracle"`, `"guestcentric"`). Not used for branching logic today, but keep it accurate — it is a natural key to grep by. |
| `auth_type` | `"oauth2_client_credentials"` or `"basic_or_jwt"` — see the table above. Drives real branching in `integration_client.py`. |
| `documentation_url` | Link to the provider's own API docs. Shown to users, not used at runtime. |
| `auth_config` | Dict, JSON-serialized — auth-flow parameters. Shape differs per `auth_type` (below). |
| `required_fields` | List of credential-form field definitions (below). |
| `endpoints` | List of certified endpoint definitions (below). |

### `auth_config` shape per `auth_type`

**`oauth2_client_credentials` (Oracle Opera OHIP)** — the base URL (`gateway_url`) is *user-supplied* per account, so `auth_config` only carries the token-flow shape:

```python
"auth_config": {
    "token_endpoint_path": "/oauth/v1/tokens",
    "grant_type": "client_credentials",
    "scope": "urn:opc:hgbu:ws:__myscopes__",
    "token_header": "Authorization",
    "token_prefix": "Bearer",
},
```

`IntegrationClient._refresh_oauth_token` POSTs to `{gateway_url}{token_endpoint_path}` with HTTP Basic `(client_id, client_secret)` and the `client_credentials` grant (or `refresh_token` grant when a refresh token is on file). Because `gateway_url` is attacker-influenceable account input, it is validated on every use by `_validate_opera_gateway_url` against an **allow-list of Oracle hostname suffixes** (`.oraclecloud.com`, `.oracle.com`, `.ocs.oc-test.com`). **If your new integration also takes a user-supplied base URL/gateway, you must add an equivalent hostname allow-list check before using it in any outbound request** — this is an SSRF control, not incidental validation (see `threat_model.md`).

**`basic_or_jwt` (GuestCentric CRS)** — the base URL is fixed and *not* user-supplied, so it lives directly in `auth_config`:

```python
"auth_config": {
    "base_url": "https://crs-api.guestcentric.net/v1.0",
    "auth_methods": ["basic_auth", "jwt"],
    "jwt_login_endpoint": "/authentication/login",
    "jwt_refresh_endpoint": "/authentication/refresh",
    "jwt_check_endpoint": "/authentication/check_token",
    "jwt_max_lifetime_hours": 3,
    "basic_auth_query_params": ["apikey", "hotelId"],
},
```

`basic_auth_query_params` is a list of **credential keys** (not query-param values) that `_build_url` appends as query parameters on *every* request when `auth_method == "basic_auth"` — e.g. `?apikey=...&hotelId=...`. If your `basic_or_jwt` integration needs different provider-specific query params injected on every call, list the credential keys here; if it needs none, use `[]`.

Because a fixed `base_url` isn't attacker-controlled, no hostname allow-list is needed for this shape.

### `required_fields` — the credential form, including conditional fields

Each entry:

| Key | Notes |
|---|---|
| `key` | The credential dict key, referenced later by `integration_client.py` and shown as the input's form field. |
| `label` | Form label. |
| `type` | `"text"`, `"password"`, `"url"`, `"number"`, `"boolean"`, or `"select"`. `"password"` masks the input; it's still stored encrypted like every other field. |
| `placeholder` | Optional input placeholder. |
| `description` | Helper text shown under the field. |
| `required` | Whether the field is enforced client-side before Connect is allowed — only for **currently visible** fields (see `show_when`). |
| `options` / `option_labels` | Only for `type: "select"` — the option values and their display labels. |
| `show_when` | Optional dict of `{other_field_key: value}`. The field is only rendered (and only enforced as required) when **every** entry matches the current form state. |

`show_when` example, from GuestCentric — `hotelId` only makes sense for Basic Auth, since JWT sessions can span multiple hotels:

```python
{
    "key": "auth_method",
    "label": "Authentication Method",
    "type": "select",
    "options": ["basic_auth", "jwt"],
    "option_labels": {"basic_auth": "Basic Auth", "jwt": "JWT Token"},
    "required": True,
},
{
    "key": "hotelId",
    "label": "Hotel ID",
    "type": "text",
    "description": "Required for Basic Auth; not used for JWT.",
    "required": False,
    "show_when": {"auth_method": "basic_auth"},
},
```

This is rendered by `ConnectModal.tsx` / `EditModal.tsx` in `botelier/frontend/app/(dashboard)/dashboard/integrations/components/`: they iterate `required_fields` in order, evaluate `show_when` against the in-progress form state (falling back to a `select` field's first option if the user hasn't touched it yet), and hide/skip validation for any field whose condition doesn't currently hold. **`show_when` conditions are ANDed together and compared by exact string equality** — no OR, no negation.

Convention to follow for any `basic_or_jwt` integration: include a `type: "select"` field literally named **`auth_method`** whose `options` match `auth_config.auth_methods`. `IntegrationClient` reads `credentials.get("auth_method")` directly (not `auth_config`) to decide whether to skip token refresh (`basic_auth`) or run the JWT login/refresh flow (`jwt`), and to decide whether to send an `Authorization: Basic ...` header or a bearer token. Naming it anything else means the runtime will silently fall through to the JWT/OAuth path.

### `endpoints` — the certified endpoint catalog

Each entry is what a flow author sees and picks in the API Request node's **Endpoint** dropdown:

| Field | Notes |
|---|---|
| `id` | Stable slug (e.g. `"check_availability"`, `"book_reservation"`). This is the `endpointId` stored on flow nodes — **never rename or remove an `id` once any flow references it**; doing so silently breaks that node (`_resolve_endpoint` returns `None` and the node falls back to raw `config` fields, likely missing required query params). |
| `category` | Grouping label shown in the endpoint list and in the docs page's endpoint table (e.g. `"Reservations"`, `"Hotels"`, `"Search"`). |
| `name` | Human-readable endpoint name. |
| `description` | Shown under the endpoint dropdown once selected. |
| `method` | `GET` / `POST` / `PUT` / `PATCH` / `DELETE`. |
| `path` | May contain `{{variable}}` placeholders resolved from call-time variables, and credential placeholders (`{hotelId}`, `{{hotelId}}`, `{hotel_id}`, `{{hotel_id}}`) resolved from the connected account's own `hotel_id`/`hotelId` credential — see `_build_url`. Any `{{var}}` still unresolved in the path after every substitution **fails fast** (`_MissingRequiredVariables`) rather than forwarding a malformed URL upstream. |
| `query_params` | List of `{"key": ..., "value": "{{variable}}", "required": bool}`. Rendered per call; an unresolved **required** param raises a validation error (`_MissingRequiredVariables`) instead of silently sending a broken request. Unresolved optional params are simply omitted. |
| `body_template` | Dict (or JSON string) with `{{variable}}` placeholders, used for `POST`/`PUT`/`PATCH` when the flow node doesn't supply its own `bodyTemplate`. |
| `variables` | List describing every placeholder used above: `{key, type, label, description, placeholder, required, default}`. These populate the API Request node's **test panel** inputs. `"default": "today"` is a special sentinel resolved to the current UTC date at call time; any other `default` is passed through as a literal fallback when the caller doesn't supply that variable. |
| `response_mapping` | Dict: `flow_variable_key -> JSONPath`. Extracted via the shared `extract_json_value` (see below) after a successful (2xx) response, and offered as the endpoint's default response mapping when selected in the API Request node. |
| `response_mapping_labels` | Dict, same keys as `response_mapping` — a human-readable one-line description of what that extracted value is. Purely presentational: shown under each auto-populated mapping row in the API Request node, and worth listing in your integration's docs page endpoint table. |

Two representative real examples (trimmed) — a `GET` with query params (GuestCentric `search_hotels`-style) and a `POST` with a body template (GuestCentric `book_reservation`):

```python
{
    "id": "check_availability",
    "category": "Hotels",
    "name": "Hotel Rooms & Rates",
    "description": "Get available rooms, rates, and promotions for a hotel.",
    "method": "GET",
    "path": "/hotels/{{hotel_id}}/rooms",
    "query_params": [
        {"key": "checkin",  "value": "{{checkin}}",  "required": True},
        {"key": "checkout", "value": "{{checkout}}", "required": True},
        {"key": "adults",   "value": "{{adults}}",   "required": True},
    ],
    "variables": [
        {"key": "hotel_id", "type": "text", "label": "Hotel ID", "required": True},
        {"key": "checkin",  "type": "date", "label": "Check-in Date", "required": True},
        {"key": "checkout", "type": "date", "label": "Check-out Date", "required": True},
        {"key": "adults",   "type": "number", "label": "Adults", "required": True},
    ],
    "response_mapping": {
        "available_rooms": "$.rooms[*].name",
        "rates":           "$.rooms[*].rate_plans[*].name",
    },
    "response_mapping_labels": {
        "available_rooms": "Names of available room types",
        "rates":           "Names of available rate plans",
    },
},
{
    "id": "book_reservation",
    "category": "Reservations",
    "name": "Book Reservation",
    "method": "POST",
    "path": "/reservations/book",
    "body_template": {
        "reservations": [{
            "action": "new",
            "status": "confirmed",
            "checkin": "{{checkin}}",
            "checkout": "{{checkout}}",
            "guest": {"first_name": "{{guest_first_name}}", "last_name": "{{guest_last_name}}"},
        }]
    },
    "variables": [
        {"key": "checkin", "type": "date", "label": "Check-in Date", "required": True},
        {"key": "checkout", "type": "date", "label": "Check-out Date", "required": True},
        {"key": "guest_first_name", "type": "text", "label": "Guest First Name", "required": True},
        {"key": "guest_last_name", "type": "text", "label": "Guest Last Name", "required": True},
    ],
    "response_mapping": {
        "crs_reservation_code": "$.reservations[0].crs_reservation_code",
        "status":               "$.reservations[0].status",
    },
    "response_mapping_labels": {
        "crs_reservation_code": "CRS reservation code (primary confirmation reference)",
        "status":               "Reservation status (confirmed/cancelled)",
    },
},
```

For the full, real endpoint catalogs (15 GuestCentric endpoints, several Opera OHIP endpoints), read `guestcentric_integration.py` and `opera_integration.py` directly — don't hand-copy an outdated snapshot from this guide.

:::caution Booking flows: "names" are not always bookable codes
If your booking endpoint needs a code that isn't the same string a guest would say out loud (e.g. a `cancellation_policy_id` or `room_rate_code` that isn't returned by the availability search the guest sees), a single API node mapping display **names** into response variables is not enough — the flow needs a **second, filtered API call** to resolve the guest's chosen name back into the exact ID the booking endpoint requires. See the `GUESTCENTRIC_CRS_BOOKING_TEMPLATE` flow template for the working pattern (a `confirm_room_rate` / `check_cancellation_policy`-style follow-up API node between selection and booking).
:::

## Step 2 — Register the seed

Add your seed to `botelier/backend/botelier/seeds/__init__.py` inside `seed_all_integrations`, following the existing two entries exactly:

```python
try:
    from botelier.seeds.<name>_integration import seed_<name>_integration
    seeds.append(("<name>", "<slug>", seed_<name>_integration))
except ImportError as exc:
    logger.warning(f"Could not import <name> seed: {exc}")
```

`seed_all_integrations` runs every registered seed (each wrapped so one failure doesn't block the others), then calls `verify_seed(slug, db)` for each — which checks the row exists and that `endpoints_config` / `required_fields` have the shape described above, logging (not raising) a warning if anything is missing. There is nothing else to wire up on the backend: `seed_all_integrations` is called from app startup, and it is idempotent, so a fresh seed module takes effect on the next backend restart with no migration needed.

## Step 3 — Auth and runtime behavior (what `IntegrationClient` actually does)

All of this lives in `botelier/backend/botelier/services/integration_client.py`. You don't need to write any of it for a new integration — read this section so you can predict how your seed's fields will be used, and debug when something doesn't resolve as expected.

**Per-request flow (`execute_request`):**
1. Loads the `AccountIntegration` (scoped to `account_id` — cross-tenant lookups are impossible by construction) and rejects if not `CONNECTED`.
2. Decides if a token is needed at all: `basic_or_jwt` + `auth_method == "basic_auth"` never needs a token; every other combination does.
3. If a token is needed and `_token_needs_refresh` is true (expired, or within a 60-second proactive skew of expiry), refreshes it via `_refresh_token_with_lock` — a **cross-worker Postgres advisory lock** keyed on the integration UUID, so a burst of concurrent calls triggers exactly one provider login instead of one per in-flight request (critical for providers that rotate refresh tokens on use).
4. Resolves the certified `endpoint_def` by `endpoint_id`, merges endpoint-declared variable `default`s under caller-supplied variables, then builds the URL (`_build_url`), headers (`_build_headers`), and body (`_build_body`).
5. Executes via `httpx` through an SSRF-safe transport, retrying on timeout/network errors up to `retry_count` times.
6. On a 2xx response, extracts `response_mapping` values via `extract_json_value` into `extracted_variables`. Non-2xx responses are classified into `auth_error` / `not_found` / `validation_error` / `server_error` and mapped to caller-facing messages.
7. Every attempt (success or failure) is written to `IntegrationCallLog` with the endpoint/URL **sanitized** (query string stripped, `{{secrets.*}}` placeholders redacted) before persisting — never log raw credentials or query strings.

**Token refresh, per `auth_type`/`auth_method` (`_refresh_token`):**
- `basic_or_jwt` + `auth_method == "basic_auth"` → no-op, always "fresh" (there is no token).
- `basic_or_jwt` + `auth_method == "jwt"` → `_refresh_jwt_token`: tries the refresh-token endpoint first if a refresh token is on file, falls back to a fresh login with `username`/`password` otherwise. A **transient** failure (network exception) leaves the integration `CONNECTED` so the next call retries automatically; a **definitive** rejection (non-200 from the provider) sets status to `TOKEN_EXPIRED`, which requires a manual reconnect.
- `oauth2_client_credentials` → `_refresh_oauth_token`: validates `gateway_url` against the Oracle hostname allow-list, then POSTs to the token endpoint with HTTP Basic `(client_id, client_secret)`. Same transient-vs-definitive failure handling as above.

**Provider-specific injected params (`_build_headers` / `_build_url`):**
- `oauth2_client_credentials`: always injects `x-app-key` (from the `app_key` credential, falling back to `client_id`), `x-hotelid` (from `hotel_id`), and — when present — `x-chainid` (from `chain_code`), on top of the `Authorization: Bearer <token>` header.
- `basic_or_jwt` + `basic_auth`: sends `Authorization: Basic base64(username:password)` and appends every key listed in `auth_config.basic_auth_query_params` (that has a stored credential value) as a URL query parameter — e.g. `apikey` and `hotelId` for GuestCentric.
- `basic_or_jwt` + `jwt`: sends `Authorization: Bearer <access_token>`, no extra query params unless you add them via `basic_auth_query_params` handling — note that field name only applies query params for the `basic_auth` branch today.
- Any `headers` set explicitly on the flow node's `IntegrationAPIConfig` are merged in last and win over these defaults.

**Response extraction (`extract_json_value`, shared with the flow executor so every integration and flow node resolves paths identically):**
- `$` / `$.` root prefix (optional), dot keys (`a.b.c`), bracket index (`a[0].b`), legacy dot index (`a.0.b`), and wildcard (`a[*].b`) which expands across list elements and flattens/dedupes the result into a list.
- Returns `None` (not an exception) when a path resolves to nothing, so `default_value`s and optional response variables degrade gracefully.

### Property-level constants: `connection_config`

Every `AccountIntegration` row carries an optional `connection_config` JSON blob (`get_connection_config()` / `set_connection_config()`) for **per-connection constants that never change call-to-call** — e.g. a `hotel_id`, `hotel_name`, reservations email, or a default currency for that specific property. It participates in variable resolution at two points, both as the lowest-priority layer:

- **`IntegrationClient._apply_endpoint_defaults`** merges it in **under** endpoint variable `default`s and **under** caller-supplied `collected_slots`. A value collected from the caller (or an endpoint default) always wins over a `connection_config` constant of the same key.
- **`flow_executor._inject_connection_config_to_slots`** copies each key into the flow's `collected_slots` **non-destructively** before an integration API node runs, so `{{hotel_id}}`-style placeholders in a `path`, `query_params`, `body_template`, or a `SET_VARIABLE` node resolve without re-collecting the value from the caller every turn. It never overwrites a slot the flow already set, and a missing or malformed blob is logged at DEBUG and never blocks the flow.

There is **no built-in UI or API route to edit `connection_config` for account integrations today** — it's populated out-of-band (a one-off script or direct row update); only the separate MCP-connection model exposes it through an endpoint. If your integration needs property-level constants, document which keys you expect and how an operator is expected to set them. Do not confuse this with `connection_name`, which *is* set in the Connect/Edit modal and only labels the connection in the flow-editor dropdown (see Step 4).

## Step 4 — Flow-editor wiring

Nothing needs to be hand-wired for endpoints to appear — `APIRequestNodePanel.tsx` fetches connected integrations from `/api/integrations/connections` and reads `integration_type.endpoints` directly off whatever your seed produced. Concretely, once your seed is registered and an account has connected:

1. In an **API Request** node, setting **API Source** to `Integration` reveals a **Connected Integration** dropdown and, once selected, an **Endpoint** dropdown listing every `endpoints[].name` (flat — use `category` in your own docs table for grouping). The Connected Integration dropdown supports **named connections**: an account with a single connection shows one entry (its `connection_name`, defaulting to your integration's `name`), while an account with **multiple connections of the same type** shows them inside an `<optgroup>` labelled by the integration type name, each option showing its own `connection_name`. This is what lets one account connect the *same* integration more than once (e.g. two GuestCentric properties) and pick the right connection per node — so always give connections a meaningful **Connection Name** at connect time.
2. Selecting an endpoint auto-populates: HTTP method + path, a JSON `bodyTemplate` (stringified from `body_template` for POST/PUT/PATCH), and the **Response Mapping** section from `response_mapping` — each auto-populated row is tagged `auto` and shows its `response_mapping_labels` description beneath it. Editing a mapping's key or path detaches it from `auto` tracking; switching to a different endpoint with existing customized mappings prompts the user before overwriting them.
3. If the selected endpoint declares `query_params`, the panel renders a collapsible **Query Parameters** section listing every param with a **Required**/**Optional** badge and the `label`/`description` pulled from the matching `variables` entry — matched by param key, falling back to the `{{var}}` name embedded in the seed's `value`. Each row is pre-filled with the seed default and can be **overridden per node**: type a literal, a different `{{variable}}`, or blank it out. Overrides are stored **sparsely** on the node as `api.queryParamOverrides` (`{ param_key: template }`); a param you never touch keeps using the seed default, so later seed changes automatically apply to untouched params, while touched params keep the author's override. Blanking a **required** param is flagged inline and blocks the **Run test** button, and also fails fast at runtime (`_MissingRequiredVariables`). Overrides are cleared when you switch endpoints (they're keyed to the endpoint's params), but are **preserved** when a pre-wired template resolves its `integrationId`.
4. The **Run test** button in the node panel calls `POST /api/api-tester/test`, which — for `apiSource: "integration"` — goes through the exact same `IntegrationClient` code path described in Step 3 (not a separate mock), so a passing test in this panel is a reliable signal the endpoint works for real. Query-param overrides are sent as `queryParamOverrides` and applied identically to a live call.
5. The panel's own test-parameter inputs are generated from your endpoint's `variables` array (`label`, `required`, `placeholder`, `description`, `type` all flow straight through).

### Optional: a pre-wired flow template

If your integration is commonly used the same way every time (e.g. "check availability, then book"), ship a flow template so users don't have to wire nodes by hand. This is entirely in `botelier/frontend/components/flow-editor/store.ts` and is optional — endpoints work in ad-hoc flows without one.

1. Define a template object with `variables`, `nodes`, and `edges` (see `GUESTCENTRIC_CRS_BOOKING_TEMPLATE` / `OPERA_OHIP_BOOKING_TEMPLATE` in `store.ts` for the full shape). Any `api_request` node should set:
   ```ts
   api: {
     apiSource: "integration",
     integrationId: "",              // left blank — resolved per-account at apply time
     integrationSlug: "<your-slug>", // must match the seed's slug exactly
     endpointId: "<endpoint id>",    // must match an id in your seed's endpoints
     ...
   }
   ```
   `APIRequestNodePanel.tsx` auto-resolves `integrationSlug` → the account's actual `integrationId` the moment the panel loads, *as long as the account has exactly one connection to that integration type* — this is why `integrationId` is left blank in template authoring.
2. Register the template object in the `TEMPLATES` map (keyed by a template id) and add a matching entry to the `AVAILABLE_TEMPLATES` array (`{ id, name, description, complexity? }`) near the bottom of `store.ts`.
3. That's it for the picker — `FlowToolbar.tsx`'s **Templates** dropdown renders `AVAILABLE_TEMPLATES` directly; no separate registration file exists.
4. Mention the template by name in your integration's docs page (see Step 5) so users know it exists — the picker itself has no room for a long description.

## Step 5 — Docs page

Every pre-built integration gets its own page under `docs-site/docs/integrations/`. Use `oracle-opera-ohip.md` or `guestcentric-crs.md` as your starting template — copy one and adapt it. At minimum, include:

```md
---
id: <your-slug-or-short-id>
title: <Integration Display Name>
sidebar_label: <Short Label>
---

# <Integration Display Name> Integration

One-paragraph summary of what it connects to and what it lets the assistant do.

## Prerequisites
- Account/API access requirements
- Every credential the user will need, matching your `required_fields` keys and their descriptions

## Setup in Botelier
1. Integrations → Connect Integration → select this integration
2. A table mapping each visible form field (including any `show_when`-conditional ones, noted as such) to what to enter
3. What happens on Connect (token exchange, validation, etc.)

## Available Endpoints / Actions
A table of `category` | endpoint `name` | `description` — this is your endpoint catalog's human-facing index. Keep it in sync with your seed's `endpoints`.

## Linking to an Assistant
Steps to add an API Request node, toggle to this integration, pick an endpoint, and (if you built one) mention the flow template by name.

## Testing the Connection
Point to the API Tester (Tools → API Tester) with a concrete endpoint + known-good sample input to try.

## Refreshing Credentials / Security Notes
Anything specific to your auth flow: token refresh behavior, what to do if credentials change, or any hostname/URL validation a user-supplied base URL is subject to.
```

Then wire it into navigation — two edits, both required:

1. **Sidebar** — add your doc's `id` to the `Integrations` category's `items` array in `docs-site/sidebars.js`, alongside the existing `integrations/oracle-opera-ohip` and `integrations/guestcentric-crs` entries.
2. **Overview page** — add a row for your integration to the **Pre-Built Integrations** table in `docs-site/docs/integrations/integrations-overview.md`, linking to your new page.

## Step 6 — Testing before you call it done

Test at both layers — they exercise different code paths:

1. **API Tester** (`Tools → API Tester` in the dashboard, or the **Run test** button inside an API Request node's panel) — exercises the real `IntegrationClient` request pipeline (auth, token refresh, URL/header/body building, response extraction) for one endpoint at a time, against your **actual connected account**. This is the fastest way to confirm an individual endpoint's `path`, `query_params`, `body_template`, and `response_mapping` are all correct against the live provider.
2. **Flow simulator** (`Flow Editor → Simulate`, backed by `POST /api/simulation/start` + `/api/simulation/message`) — runs your endpoint inside a full flow, so you can confirm variable collection prompts, response mapping into flow variables, and the AI's `response_instructions`-driven narration all work together end-to-end. This is the only way to catch issues like a booking node needing a second filtered lookup (see the callout in Step 1) — those only show up when you actually walk the flow.

Do both before considering the integration done. A green API Tester result only proves the HTTP contract is correct, not that a flow author (or the AI) can actually use it correctly inside a conversation.

## Checklist — every file to touch for a new integration

- [ ] `botelier/backend/botelier/seeds/<name>_integration.py` — new seed module (`IntegrationType` dict + `seed_<name>_integration`)
- [ ] `botelier/backend/botelier/seeds/__init__.py` — register the seed in `seed_all_integrations`
- [ ] Restart the `botelier-backend` workflow so the new seed runs (no `--reload`, per the backend gotcha in `replit.md`)
- [ ] *(optional)* `botelier/frontend/components/flow-editor/store.ts` — add a `TEMPLATE` object, register it in the `TEMPLATES` map, and add an entry to `AVAILABLE_TEMPLATES`
- [ ] `docs-site/docs/integrations/<your-page>.md` — new docs page (copy `oracle-opera-ohip.md` or `guestcentric-crs.md` as a starting point)
- [ ] `docs-site/sidebars.js` — add your doc's `id` under the `Integrations` category
- [ ] `docs-site/docs/integrations/integrations-overview.md` — add a row to the **Pre-Built Integrations** table
- [ ] Verify in the dashboard: connect the integration, confirm every `required_fields` entry (including `show_when`-conditional ones) renders correctly
- [ ] Verify with the **API Tester**: test at least one `GET` and one `POST`/`PUT` endpoint end-to-end against the real provider
- [ ] Verify with the **Flow simulator**: walk a flow using an API Request node wired to this integration, confirm response mapping and AI narration both work
- [ ] If your integration exposes a booking-style endpoint that needs an ID/code the guest wouldn't say out loud, confirm your flow includes a second, filtered lookup step to resolve it (see the callout in Step 1)
