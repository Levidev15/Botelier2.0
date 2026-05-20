---
id: admin-overview
title: Admin Overview
sidebar_label: Admin Overview
---

# Admin Overview

The **Admin Panel** is for **platform administrators** — users with the `platform_admin` user type. It provides cross-account visibility, account management, billing configuration, and platform-level settings.

:::note Access Restriction
The Admin Panel is not accessible to regular account users, regardless of their account-level role. Only users with `platform_admin` status can access `/admin/*` routes.
:::

## How to Access the Admin Panel

1. Log in with a platform admin account.
2. Click the **Admin** link in the top navigation bar (visible only to platform admins).
3. The admin panel opens with the **Accounts** table as the default view.

## Admin vs. Account-Level Settings

| Scope | Who Can Access | What It Controls |
|---|---|---|
| **Account Settings** | Account Admin | Single account config (assistant, team, billing rates view) |
| **Admin Panel** | Platform Admin | All accounts, platform billing rates, user management, SMTP, feature flags |

## Admin Panel Sections

| Section | Purpose |
|---|---|
| [Managing Accounts](./managing-accounts) | Create accounts, view usage, configure billing, manage feature flags |
| [Managing Users](./managing-users) | View all platform users, support sessions, password resets |
| [Platform Billing](./platform-billing) | Cross-account usage table, platform rate config, cost analysis |
| [Platform Settings](./platform-settings) | SMTP config, feature catalog defaults, alert email testing |
| [Security Log](./security-log) | Platform security event log — blocked calls, webhook failures |

## Support Sessions (Impersonation)

Platform admins can open a **support session** to view any account as if they were a member of that account. This is used for debugging customer issues.

During a support session:
- A banner at the top of the screen indicates you are in a support session
- All actions are performed as the support session admin, not as the account user
- Support session activity is logged in the security event log

To start a support session:
1. Go to **Admin** → **Accounts** → select an account.
2. Click **Open Support Session**.

To end a support session:
1. Click **End Support Session** in the top banner.
