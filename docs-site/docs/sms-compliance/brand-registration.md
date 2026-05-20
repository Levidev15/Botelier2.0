---
id: brand-registration
title: Brand Registration
sidebar_label: Brand Registration
---

# Brand Registration

A **Brand** represents your legal business entity in the A2P 10DLC system. You must register a brand before creating any campaigns.

## Prerequisites

- EIN (Employer Identification Number) for US businesses — or equivalent tax ID for non-US entities
- Legal business name matching your EIN filing
- Business website
- Business address and phone number
- Primary contact email

## Step-by-Step Registration

1. Navigate to **SMS** → **Compliance** → **Brands**.
2. Click **Register Brand**.
3. Fill in all required fields:

| Field | Notes |
|---|---|
| **Legal Business Name** | Must match your EIN registration exactly |
| **EIN / Tax ID** | US businesses: 9-digit EIN (no dashes). Non-US: select country and enter equivalent |
| **Business Type** | LLC, Corporation, Partnership, Sole Proprietor, Non-Profit |
| **Business Industry** | Select the closest match (e.g. "Healthcare", "Real Estate", "Retail") |
| **Website URL** | Must be publicly accessible |
| **Business Address** | Street, city, state, ZIP, country |
| **Support Email** | Customer-facing support email |
| **Support Phone** | Customer-facing support number |

4. Review the information — errors here may cause TCR rejection and delay registration.
5. Click **Submit Brand Registration**.

## After Submission

Botelier submits the registration to TCR via Twilio. The brand status will be one of:

| Status | Meaning |
|---|---|
| **Pending** | Submitted to TCR; awaiting review |
| **Approved** | Brand verified — you can create campaigns |
| **Failed** | TCR rejected the registration — see the error details |
| **Suspended** | Brand suspended by TCR or carrier |

## Checking Status

The brand status auto-refreshes every few minutes. To force a refresh, click **Refresh from TCR** on the brand detail page. This queries TCR for the latest status.

## Handling Rejections

Common rejection reasons:

- **EIN mismatch** — legal name doesn't match IRS records. Verify using the [IRS EIN lookup](https://www.irs.gov/).
- **Missing website** — ensure the website URL is publicly accessible and represents the business.
- **PO Box address** — most carriers require a physical street address.
- **High-risk industry** — some industries (cannabis, firearms, lending) require manual review.

To re-submit after fixing issues:
1. Click **Edit Brand**.
2. Correct the errors.
3. Click **Re-submit**.

:::note One Brand Per Business
You typically only need one brand per legal entity. Multiple brands for the same EIN are flagged by TCR. If you operate multiple product lines under different names but the same legal entity, use one brand and create separate campaigns per product line.
:::
