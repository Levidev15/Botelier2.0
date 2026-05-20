---
id: billing-alerts
title: Billing Alerts
sidebar_label: Billing Alerts
---

# Billing Threshold Alerts

**Billing Alerts** notify platform admins and the account owner when an account's month-to-date (MTD) spend crosses a configured threshold.

## What the Alert Does

After each call completes, Botelier computes the account's total MTD spend (inbound calls + outbound transfers + SMS). If the total first crosses the configured threshold in the current calendar month, an email is sent to:

1. All **platform administrators**
2. The **account owner** (primary user with admin role on the account)

The email includes:
- Account name
- Current MTD spend
- The threshold that was crossed
- A link to the admin billing detail page

## Setting the Threshold

The billing alert threshold is set per account by a **platform administrator**:

1. Go to **Admin** → **Accounts** → select the account → **Billing** tab.
2. Enter the **Monthly Alert Threshold (USD)** amount.
3. Click **Save**.

Setting the threshold to `0` or leaving it blank disables alerts for that account.

## Duplicate Suppression

Only **one alert email is sent per account per calendar month**, regardless of how much further the spend grows. The suppression is handled by an atomic database insert — duplicate alerts are blocked at the database level.

If spend continues to grow after the first alert, no additional emails are sent for that month. The counter resets on the first day of the next calendar month.

## Alert Delivery and SMTP

Alerts are sent via SMTP using the platform-wide email settings configured by your Botelier administrator. Required environment variables:

| Variable | Description |
|---|---|
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_PORT` | SMTP port (typically 587 or 465) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `ALERT_EMAIL_FROM` | Sender address for alert emails |

If SMTP is not configured, billing alerts are silently skipped (no error is logged, no alert is stored). Configure SMTP in **Admin** → **Settings** → **Email Config**.

## What To Do If No Alert Arrives

If you expected an alert but didn't receive one:

1. **Check SMTP configuration** — Admin → Settings → Email Config. Use **Send Test Alert** to verify delivery.
2. **Check whether the threshold was already triggered this month** — if an alert was already sent this calendar month, no additional alerts will be sent. Check **Admin** → **Accounts** → account detail → **Billing** → **Last Alert Sent**.
3. **Verify the threshold value** — ensure it's set to a value the MTD spend actually crosses.
4. **Check the account owner's email** — the alert goes to the platform-level user account. Confirm the address is correct.
5. **Check spam/junk** — alert emails may be filtered if the sending domain isn't configured with SPF/DKIM records.

## SMS Billing Alerts

Billing alerts include SMS costs in the MTD total. SMS spend is calculated using the same rates as the Usage Summary page. A single threshold covers all channels (voice + SMS).

## Admin: Test Alert Email

Platform admins can trigger a test alert email to verify SMTP is working:

1. Go to **Admin** → **Settings** → **Email Config**.
2. Click **Send Test Billing Alert**.
3. Enter an email address to send the test to.
4. Click **Send**.

A test email is sent immediately without affecting the alert suppression state.
