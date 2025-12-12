# Multi-Property Support Feature Plan

## Overview
Enable management companies to manage multiple hotels/properties within a single Botelier account, with isolated resources (KB, tools, assistants) per property.

## Current State
- Account = top-level tenant
- All resources (assistants, KB, tools, phone numbers) belong directly to account_id
- No isolation between properties under the same company

## Proposed Architecture

### Data Model Changes

#### New Table: `properties`
```sql
CREATE TABLE properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    address TEXT,
    timezone VARCHAR(50),
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Modified Tables (add property_id)
- `assistants` - add `property_id UUID REFERENCES properties(id)` (nullable for global)
- `tools` - add `property_id UUID REFERENCES properties(id)` (nullable for global)
- `knowledge_entries` - add `property_id UUID REFERENCES properties(id)` (nullable for global)
- `phone_numbers` - add `property_id UUID REFERENCES properties(id)` (nullable for global)
- `call_logs` - add `property_id UUID` (for filtering/reporting)
- `assistant_dispositions` - inherits property from assistant

#### New Table: `user_property_access`
```sql
CREATE TABLE user_property_access (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    property_id UUID NOT NULL REFERENCES properties(id),
    access_level VARCHAR(50) DEFAULT 'full', -- 'full', 'readonly', 'none'
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, property_id)
);
```

### Hierarchy Diagram
```
Account (Management Company: "Hospitality Group Inc")
│
├── Property 1 (Hotel A - Downtown)
│   ├── Assistant: "Front Desk AI"
│   ├── KB: Check-in/out times, amenities, local info
│   ├── Tools: booking_flow, room_service_flow
│   └── Phone: +1-555-0101
│
├── Property 2 (Hotel B - Airport)
│   ├── Assistant: "Airport Concierge"
│   ├── KB: Shuttle schedules, flight info, parking
│   ├── Tools: shuttle_booking_flow, parking_flow
│   └── Phone: +1-555-0202
│
└── Global Resources (Shared)
    ├── Transfer tools (billing, HR)
    └── Company-wide KB entries
```

## Backend Changes

### API Endpoints

#### Property Management
- `GET /api/properties` - List all properties for account
- `POST /api/properties` - Create new property
- `GET /api/properties/:id` - Get property details
- `PUT /api/properties/:id` - Update property
- `DELETE /api/properties/:id` - Deactivate property

#### User Property Access
- `GET /api/properties/:id/users` - List users with access
- `POST /api/properties/:id/users` - Grant user access
- `DELETE /api/properties/:id/users/:userId` - Revoke access

#### Scoped Resource Endpoints
All existing endpoints gain optional `property_id` query param:
- `GET /api/assistants?property_id=xxx`
- `GET /api/knowledge?property_id=xxx`
- `GET /api/tools?property_id=xxx`
- etc.

### Service Layer Changes
- Add `PropertyService` for CRUD operations
- Modify all resource services to scope queries by property_id
- Add middleware to extract current property from request context
- Add validation to prevent cross-property resource access

### Security Considerations
- Middleware validates user has access to requested property
- All queries MUST include both account_id AND property_id
- Cross-property resource references blocked at service layer
- Audit logging for property-level actions

## Frontend Changes

### Property Switcher Component
- Persistent dropdown in dashboard header
- Shows current property name
- Lists all accessible properties
- "Manage Properties" link for admins

### Property Management Page
- List all properties with status
- Create/edit property modal
- User access management per property
- Property settings (timezone, address, etc.)

### Scoped Views
All resource lists filter by selected property:
- Assistants page shows only current property's assistants
- KB page shows only current property's entries
- Tools page shows only current property's tools
- Call Logs can filter by property

### Creation Flows
- When creating assistant/KB/tool, auto-assign to current property
- Option to mark as "Global" (account-wide)

## Migration Strategy

### Phase 1: Database Schema
1. Create `properties` table
2. Add `property_id` columns (nullable) to existing tables
3. Create `user_property_access` table

### Phase 2: Default Property Creation
1. For each existing account, create a "Default" property with `is_default=true`
2. Backfill all existing resources with this default property_id
3. Grant all existing users access to default property

### Phase 3: Backend Updates
1. Update all services to respect property_id
2. Add property validation middleware
3. Update API endpoints with property scoping
4. Maintain backward compatibility (null property_id = global)

### Phase 4: Frontend Updates
1. Add property switcher to dashboard layout
2. Create property management pages
3. Update all resource pages to filter by property
4. Update creation forms to assign property

### Phase 5: Polish
1. Property-level analytics/reporting
2. Bulk resource transfer between properties
3. Property templates for quick setup

## User Stories

1. As an account admin, I can create multiple properties for my hotels
2. As an account admin, I can assign users to specific properties
3. As a property manager, I can only see resources for my assigned properties
4. As a property manager, I can create KB entries specific to my property
5. As a caller, I get property-specific responses when calling that hotel's number

## Estimated Effort

| Component | Estimate |
|-----------|----------|
| Database migrations | 2-3 hours |
| Backend services & APIs | 4-6 hours |
| Property management UI | 3-4 hours |
| Property switcher & scoping | 2-3 hours |
| Data migration scripts | 1-2 hours |
| Testing & polish | 2-3 hours |
| **Total** | **14-21 hours** |

## Open Questions

1. Should phone numbers be property-specific or shareable?
2. Should roles/permissions vary by property or be account-wide?
3. How to handle Twilio sub-accounts - one per property or per account?
4. Should call logs be visible across all properties for admins?

## Success Metrics

- Management companies can onboard multiple properties
- Zero cross-property data leakage
- No regression in single-property account workflows
- Property switching under 100ms
