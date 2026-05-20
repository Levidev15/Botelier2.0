---
id: team-management
title: Team Management
sidebar_label: Team Management
---

# Team Management

The **Team** section lets account administrators invite users, assign roles, and revoke access.

## Roles

| Role | Description |
|---|---|
| **Admin** | Full access to all account features including billing, team management, and all configuration |
| **Staff** | Can manage assistants, flows, knowledge bases, and view analytics — cannot manage billing or team |
| **Viewer** | Read-only access to assistants, analytics, and call logs |

Roles are scoped to the account — a user can have different roles on different accounts.

## Inviting Team Members

1. Navigate to **Team** → **Members**.
2. Click **Invite Member**.
3. Enter the invitee's **email address**.
4. Select their **role**.
5. Click **Send Invitation**.

An email is sent to the invitee with a link to create their Botelier account (or to log in and accept the invitation if they already have an account). Invitation links expire after 7 days.

## Pending Invitations

Pending invitations appear in the **Pending** tab with:
- Email address
- Role assigned
- Expiry date
- **Resend** and **Cancel** actions

If an invitation expires, cancel it and send a new one.

## Managing Existing Members

The **Members** tab shows all active team members:

| Column | Description |
|---|---|
| **Name** | User's display name |
| **Email** | Login email |
| **Role** | Current role on this account |
| **Joined** | Date they accepted the invitation |
| **Last Active** | Last login timestamp |
| **Actions** | Edit role, Revoke access |

### Changing a Role

1. Click the **...** menu on a member's row.
2. Select **Edit Role**.
3. Choose the new role.
4. Click **Save**.

The new role takes effect immediately.

### Revoking Access

1. Click the **...** menu on a member's row.
2. Select **Revoke Access**.
3. Confirm.

Revoking access removes the user's membership from this account immediately. Their Botelier account (for other accounts) is unaffected. They will receive a 403 error if they attempt to access this account's data.

## Account Owner

Each account has one **Owner** — the user designated as the primary point of contact. Owners receive billing threshold alert emails. To change the owner, contact your platform administrator.
