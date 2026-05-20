---
id: permissions-reference
title: Permissions Reference
sidebar_label: Permissions Reference
---

# Permissions Reference

This page lists every named permission in Botelier and which default role grants it.

## Role Hierarchy

| Role | Inherits From | Description |
|---|---|---|
| **Viewer** | — | Read-only access |
| **Staff** | Viewer | Operational access (manage assistants, flows, KBs, tools) |
| **Admin** | Staff | Full account access |
| **Platform Admin** | — | Cross-account platform management (separate from account roles) |

## Permission Table

| Permission | Viewer | Staff | Admin | Platform Admin | Description |
|---|---|---|---|---|---|
| `assistants.view` | ✅ | ✅ | ✅ | ✅ | List and read assistants |
| `assistants.create` | ❌ | ✅ | ✅ | ✅ | Create new assistants |
| `assistants.edit` | ❌ | ✅ | ✅ | ✅ | Edit assistant configuration |
| `assistants.delete` | ❌ | ❌ | ✅ | ✅ | Delete assistants |
| `flows.view` | ✅ | ✅ | ✅ | ✅ | View flow configurations |
| `flows.edit` | ❌ | ✅ | ✅ | ✅ | Edit and save flows |
| `knowledge_base.view` | ✅ | ✅ | ✅ | ✅ | List and read knowledge bases |
| `knowledge_base.create` | ❌ | ✅ | ✅ | ✅ | Create knowledge bases |
| `knowledge_base.edit` | ❌ | ✅ | ✅ | ✅ | Edit entries |
| `knowledge_base.delete` | ❌ | ❌ | ✅ | ✅ | Delete knowledge bases |
| `knowledge_base.import` | ❌ | ✅ | ✅ | ✅ | Import entries via CSV or URL |
| `tools.view` | ✅ | ✅ | ✅ | ✅ | View tools and tool sets |
| `tools.create` | ❌ | ✅ | ✅ | ✅ | Create tools |
| `tools.edit` | ❌ | ✅ | ✅ | ✅ | Edit tools |
| `tools.delete` | ❌ | ❌ | ✅ | ✅ | Delete tools |
| `integrations.view` | ✅ | ✅ | ✅ | ✅ | View integrations |
| `integrations.manage` | ❌ | ❌ | ✅ | ✅ | Connect, test, and delete integrations |
| `call_recording` | ❌ | ✅ | ✅ | ✅ | Access call recordings |
| `qa_scoring` | ✅ | ✅ | ✅ | ✅ | View ACW QA scores |
| `usage.view` | ❌ | ✅ | ✅ | ✅ | View usage summary and billing |
| `usage.export` | ❌ | ❌ | ✅ | ✅ | Export call data as CSV |
| `billing_rates.view` | ❌ | ❌ | ✅ | ✅ | View billing rate configuration |
| `billing_rates.manage` | ❌ | ❌ | ❌ | ✅ | Create and edit billing rates (admin only) |
| `team.view` | ❌ | ✅ | ✅ | ✅ | View team members |
| `team.manage` | ❌ | ❌ | ✅ | ✅ | Invite and revoke team members |
| `sms.view` | ✅ | ✅ | ✅ | ✅ | View SMS conversations |
| `sms.reply` | ❌ | ✅ | ✅ | ✅ | Send SMS replies as a human agent |
| `sms.manage` | ❌ | ❌ | ✅ | ✅ | Configure SMS settings |
| `phone_numbers.view` | ✅ | ✅ | ✅ | ✅ | View phone numbers |
| `phone_numbers.manage` | ❌ | ❌ | ✅ | ✅ | Purchase, assign, and release numbers |

## Custom Permissions

Platform administrators can grant individual permissions to a user beyond their default role. Contact your Botelier administrator if you need a specific permission not included in your role.

## Permission Enforcement

All permissions are enforced server-side at the API edge. Frontend UI elements may hide buttons for unauthorized actions, but the backend will reject unauthorized requests regardless of UI state.

**Relevant files:**
- `botelier/backend/botelier/auth/middleware.py` — `check_account_permission()`
- `botelier/frontend/lib/auth/usePermissions.ts` — frontend hook
- `botelier/backend/botelier/auth/permissions.py` — permission schemas
