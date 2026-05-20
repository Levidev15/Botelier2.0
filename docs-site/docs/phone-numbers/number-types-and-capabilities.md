---
id: number-types-and-capabilities
title: Number Types & Capabilities
sidebar_label: Number Types & Capabilities
---

# Number Types and Capabilities

## Local Numbers

Local numbers have a specific area code and appear to callers as originating from a geographic region.

**Best for:** Customer-facing support lines where local presence matters.

**Capabilities:**
- Inbound voice ✅
- Outbound voice ✅ (requires verified caller ID)
- SMS/MMS ✅ (most US local numbers)

**A2P 10DLC:** Required for US business SMS on local numbers. See [A2P 10DLC Overview](../sms-compliance/a2p-10dlc-overview).

---

## Toll-Free Numbers

Toll-free numbers (800, 833, 844, 855, 866, 877, 888 prefixes) are free for callers to dial.

**Best for:** National customer service lines.

**Capabilities:**
- Inbound voice ✅
- SMS/MMS ✅ (after toll-free verification)
- Outbound voice ✅

**Note:** Toll-free SMS requires Toll-Free Verification (TFV) with the carrier. This is separate from A2P 10DLC registration. Apply through the Botelier admin panel or directly in the Twilio console.

---

## Mobile Numbers

Mobile (wireless) numbers are required in some countries for SMS delivery. In the US, they are used for high-volume SMS when toll-free or short code isn't available.

**Capabilities:**
- SMS/MMS ✅
- Voice ✅ (varies by country)

---

## SMS-Capable vs. Voice-Only

Not all numbers support both SMS and voice. Check the **Capabilities** column in the number search results before purchasing:

| Icon | Meaning |
|---|---|
| 📞 | Voice capable |
| 💬 | SMS capable |
| 🖼️ | MMS capable |

If you need a number for both voice calls and SMS, filter for numbers with all three capabilities.

---

## Porting Considerations

Porting an existing number to Twilio (and then into Botelier) is possible but outside Botelier's direct control. The process:

1. Initiate a port request with Twilio.
2. Twilio coordinates with your current carrier (~2–4 weeks for US numbers).
3. Once ported, the number appears in your Twilio sub-account.
4. Assign it to an assistant in Botelier.

During the port window, the number remains active with the original carrier. Botelier cannot receive calls on a number until the port is complete and the number is assigned.

**Note:** Number porting does not affect Twilio webhook configuration — Botelier will set the correct webhooks once the number appears in your sub-account.
