---
id: provisioning-numbers
title: Provisioning Phone Numbers
sidebar_label: Provisioning Numbers
---

# Provisioning Phone Numbers

Phone numbers are provisioned from Twilio and assigned to assistants. Each number has Twilio webhook URLs configured automatically by Botelier.

## Searching and Purchasing Numbers

1. Navigate to **Phone Numbers** → **Buy Number**.
2. Choose the number type:
   - **Local** — area-code-specific numbers (e.g. `+1 212 …`)
   - **Toll-Free** — `+1 800 / 833 / 844 / 855 / 866 / 877 / 888` prefixes
   - **Mobile** — mobile-capable numbers (required for SMS in some countries)
3. Enter an area code or prefix to search.
4. Select a number from the results.
5. Click **Purchase**.

The number is provisioned on your account's Twilio sub-account and appears in your phone number list immediately.

---

## Assigning a Number to an Assistant

After purchasing, assign the number:

1. Click the number in the **Phone Numbers** list.
2. Under **Assign To**, select an assistant from the dropdown.
3. Click **Save**.

Botelier automatically updates the Twilio voice URL and status callback:

| Webhook | URL |
|---|---|
| **Voice URL** | `https://<your-domain>/api/calls/inbound` |
| **Status Callback** | `https://<your-domain>/api/calls/status` |
| **SMS URL** | `https://<your-domain>/api/sms/webhook` (if SMS-capable) |

:::tip Re-sync Webhooks
If webhooks get out of sync (e.g. after a domain change), click **Re-sync Webhook** on the number detail page to force Botelier to re-push the correct URLs to Twilio.
:::

---

## A2P Number Assignment

For SMS campaigns subject to A2P 10DLC compliance, numbers must be assigned to an approved A2P campaign. See [Campaign Registration](../sms-compliance/campaign-registration) for details.

After your campaign is approved:
1. Open the phone number.
2. Under **A2P Campaign**, select the approved campaign.
3. Save.

---

## Twilio Webhook URLs

Botelier manages these Twilio webhook fields on each number:

| Field | Purpose |
|---|---|
| Voice URL | Receives incoming call notifications (POST) |
| Voice Method | Always POST |
| Status Callback URL | Receives call status events (initiated, ringing, in-progress, completed) |
| Status Callback Method | Always POST |
| SMS URL | Receives inbound SMS (POST) — SMS-capable numbers only |
| SMS Method | Always POST |

Do not modify these URLs directly in the Twilio console — changes will be overwritten on the next Botelier sync.

---

## Unassigning a Number

To remove an assistant assignment without releasing the number:
1. Open the number.
2. Set **Assign To** to **— Unassigned —**.
3. Save.

The number remains active in Twilio but incoming calls will receive a generic message or busy signal.

## Releasing a Number

To permanently release a number back to Twilio (and stop monthly charges):
1. Open the number.
2. Click **Release Number** in the danger zone.
3. Confirm.

This is irreversible. The number returns to the Twilio pool and may be assigned to another customer.
