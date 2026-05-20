---
id: campaign-registration
title: Campaign Registration
sidebar_label: Campaign Registration
---

# Campaign Registration

A **Campaign** declares a specific messaging use case and links your brand to the phone numbers used for that use case. You need at least one approved campaign before sending business SMS.

## Prerequisites

- An approved Brand (see [Brand Registration](./brand-registration))
- Clear understanding of your messaging use case

## Creating a Campaign

1. Navigate to **SMS** → **Compliance** → **Campaigns**.
2. Click **New Campaign**.
3. Fill in:

| Field | Notes |
|---|---|
| **Campaign Name** | Internal label (e.g. "Customer Support", "Appointment Reminders") |
| **Brand** | Select your approved brand |
| **Use Case** | Select the closest matching category (see below) |
| **Campaign Description** | 40–4096 characters. Describe what types of messages you send and to whom. |
| **Sample Message 1** | An actual example of a message you'll send (required) |
| **Sample Message 2** | A second example (required for most use cases) |
| **Message Flow** | How customers opt in to receive messages (required) |

## Use Case Categories

| Use Case | Description |
|---|---|
| **2FA / OTP** | One-time passwords for authentication |
| **Account Notifications** | Account status updates, alerts |
| **Customer Care** | Support, service messages |
| **Delivery Notifications** | Shipping, delivery status |
| **Fraud Alerts** | Fraud prevention messages |
| **Higher Education** | Educational institutions |
| **Marketing** | Promotional messages |
| **Mixed** | Combination of use cases (higher scrutiny) |
| **Polling / Surveys** | Customer feedback |
| **Public Service Announcement** | Non-commercial information |

:::tip Choose Carefully
Select the most specific use case matching your actual messaging. "Mixed" campaigns face higher scrutiny and lower throughput limits.
:::

## Linking a Campaign to a Brand

The campaign is automatically linked to the brand you select in step 3. One brand can have multiple campaigns (e.g. one for marketing, one for support).

## Assigning Phone Numbers

After the campaign is approved:

1. Open the campaign.
2. Click **+ Add Phone Number**.
3. Select from your available phone numbers.
4. Click **Assign**.

A number can only be in one active campaign at a time. Unassign from the current campaign before reassigning.

## Handling TCR Rejections

Common rejection reasons:

- **Sample messages don't match use case** — marketing samples on a "Customer Care" campaign
- **Missing opt-in language** — describe how customers consent to receive messages
- **Vague campaign description** — be specific about content, frequency, and audience
- **Terms of service violations** — cannabis, gambling, and other restricted industries

To fix and resubmit:
1. Click **Edit Campaign**.
2. Correct the issues.
3. Click **Re-submit to TCR**.

Each resubmission resets the review timer (~3–7 business days).

## Campaign Throughput

Approved campaigns have a **Messages Per Second (MPS)** throughput limit set by TCR based on your brand trust score and use case. Typical limits:

| Brand Type | Throughput |
|---|---|
| Standard | 1–3 MPS |
| Low-volume standard | 1 MPS |
| Starter brand (no EIN) | 0.5 MPS |

Contact Twilio support if you need higher throughput for enterprise volumes.
