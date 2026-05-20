---
id: compliance-checklist
title: Compliance Checklist
sidebar_label: Compliance Checklist
---

# A2P 10DLC Compliance Checklist

Use this checklist before sending any business SMS from US local numbers.

## Pre-Send Checklist

### Brand
- [ ] Brand registered in Botelier (**SMS** → **Compliance** → **Brands**)
- [ ] Brand status is **Approved** (not Pending or Failed)
- [ ] EIN matches IRS records exactly
- [ ] Business website is publicly accessible

### Campaign
- [ ] Campaign created and linked to the approved brand
- [ ] Campaign status is **Approved**
- [ ] Campaign use case accurately reflects your message content
- [ ] Sample messages in the campaign registration match what you actually send

### Phone Numbers
- [ ] All SMS phone numbers assigned to an approved campaign
- [ ] No unregistered numbers sending business messages

### Message Content
- [ ] Opt-in language included in the first message to new contacts: *"Reply STOP to unsubscribe"*
- [ ] No prohibited content: cannabis, gambling, firearms (without special approval), adult content, prescription drugs
- [ ] Messages only sent to contacts who have explicitly opted in
- [ ] Opt-out keywords (`STOP`, `UNSUBSCRIBE`) are honored

### Botelier Configuration
- [ ] AI SMS is enabled on the correct assistant
- [ ] Phone number assigned to the assistant matches the campaign assignment
- [ ] Test message sent and received successfully

---

## Ongoing Compliance

After going live, maintain compliance by:

1. **Honoring opt-outs immediately** — Twilio handles this automatically. Never attempt to re-message an opted-out number.
2. **Keeping message content consistent** with your campaign registration. Significant content changes may require a new campaign.
3. **Maintaining your brand registration** — update TCR if your legal business name or EIN changes.
4. **Monitoring carrier feedback scores** — high opt-out or spam complaint rates can result in campaign suspension.

---

## Prohibited Message Content

Regardless of A2P registration status, the following content types are blocked by US carriers:

- Explicit or sexual content
- Cannabis / marijuana (even in legal states) — requires special SHAFT compliance
- Firearms and ammunition sales
- Gambling and casino promotions
- Payday loans and high-risk lending
- Get-rich-quick schemes
- Phishing and spoofed sender IDs

Sending prohibited content will result in immediate campaign suspension and potential account termination.
