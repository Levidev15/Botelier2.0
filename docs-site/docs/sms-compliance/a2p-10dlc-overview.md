---
id: a2p-10dlc-overview
title: A2P 10DLC Overview
sidebar_label: A2P 10DLC Overview
---

# A2P 10DLC Overview

**A2P 10DLC** (Application-to-Person 10-Digit Long Code) is a US carrier framework that regulates business SMS sent from standard 10-digit phone numbers. It is required for any business sending SMS at scale in the United States.

:::warning Required for US Business SMS
If you send business SMS from US local phone numbers, you must complete A2P registration. Unregistered traffic is filtered or blocked by major carriers, and fines may apply for non-compliance.
:::

## Why It's Required

US mobile carriers (AT&T, T-Mobile, Verizon) implemented A2P 10DLC in 2021 to reduce spam and protect consumers. The framework ensures that:

1. Businesses are verified (brand registration)
2. The type of messages sent is declared in advance (campaign registration)
3. Phone numbers are linked to approved campaigns

## The Brand → Campaign → Phone Number Hierarchy

A2P registration follows a strict three-level hierarchy:

```
Brand (your business identity)
  └── Campaign (a declared use case + message type)
        └── Phone Numbers (assigned to the campaign)
```

| Level | What It Represents |
|---|---|
| **Brand** | Your legal business entity — EIN, legal name, address, website |
| **Campaign** | A specific messaging use case (e.g. "Customer Support", "Appointment Reminders") |
| **Phone Number** | A number assigned to one campaign; a number can only belong to one campaign |

## Registration Entities

- **TCR (The Campaign Registry)** — the central registry operated by major US carriers
- **CSP (Campaign Service Provider)** — Twilio acts as your CSP and submits registrations to TCR
- **Brand** — your company
- **Campaign** — your messaging program

Botelier submits brand and campaign data to TCR via Twilio on your behalf.

## Registration Steps

1. [Register your Brand](./brand-registration)
2. [Create and register a Campaign](./campaign-registration)
3. Assign phone numbers to the approved campaign
4. Verify compliance before sending (see [Compliance Checklist](./compliance-checklist))

## Timeline

| Step | Typical Processing Time |
|---|---|
| Brand registration | 1–3 business days |
| Campaign registration | 3–7 business days |
| Phone number assignment | Immediate after campaign approval |

## Toll-Free Numbers

Toll-free numbers (800, 833, 844, 855, 866, 877, 888) use a different verification process called **Toll-Free Verification (TFV)** and are NOT subject to A2P 10DLC. If you only use toll-free numbers for SMS, you only need TFV, not A2P registration.
