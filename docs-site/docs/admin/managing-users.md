---
id: managing-users
title: Managing Users
sidebar_label: Managing Users
---

# Managing Users

The **Users** section in the Admin Panel provides a platform-wide view of all registered users, regardless of which account they belong to.

## Accessing the User List

Navigate to **Admin** → **Users**.

## User Table

| Column | Description |
|---|---|
| **Name** | User's display name |
| **Email** | Login email address |
| **User Type** | `platform_admin` or `account_user` |
| **Accounts** | Number of accounts this user is a member of |
| **Status** | Active / Deactivated |
| **Last Login** | Most recent authentication timestamp |
| **Created** | Account creation date |

Use the search bar to filter by name or email.

## Support Sessions (Impersonation)

A support session lets you view and interact with an account as if you were a member of it. This is the primary tool for debugging customer-reported issues.

**To start a support session:**

1. From **Admin** → **Users**, find the user you want to assist.
2. Click **Open Support Session as User** or go to **Admin** → **Accounts** → account → **Open Support Session**.
3. A confirmation banner appears at the top of the page.

**During a support session:**
- You see the account's data through the user's permissions
- All your actions are logged with your platform admin identity, not the user's
- The session is temporary — it ends when you click **End Session** or close the browser tab

**To end a session:** Click **End Support Session** in the top banner.

## Resetting Passwords

To initiate a password reset for a user:

1. Open the user's detail page.
2. Click **Send Password Reset Email**.
3. A password reset email is sent to the user's registered address.

You cannot view or set a user's password directly — only the user can set their own password via the reset link.

## Deactivating Users

Deactivating a user:
- Immediately invalidates all their active sessions and API keys
- Prevents them from logging in
- Preserves all their data and account memberships

1. Open the user's detail page.
2. Click **Deactivate User**.
3. Confirm.

To reactivate, click **Reactivate User** on the same page.

## Platform Admins

To grant platform admin access to a user:

1. Open the user's detail page.
2. Toggle **Platform Admin** to on.
3. Save.

:::warning
Platform admins have unrestricted access to all accounts, all user data, and all admin functions. Grant this privilege sparingly.
:::

## Audit Trail

All admin panel actions (support sessions, user deactivations, permission changes) are recorded in the **Security Log**. See [Security Log](./security-log) for details.
