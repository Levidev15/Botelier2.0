---
id: acw-and-qa
title: After-Call Work & QA
sidebar_label: ACW & QA
---

# After-Call Work & QA

**After-Call Work (ACW)** is Botelier's automated post-call analysis system. After each call ends, the platform sends the full transcript to an LLM and returns a structured QA summary including scores, disposition, and resolution status.

## What ACW Produces

| Output | Description |
|---|---|
| **QA Score** | 0–100 numeric score based on the quality rubric you define |
| **Summary** | A concise prose summary of what happened on the call |
| **Disposition** | A classification label (e.g. "Reservation Made", "Complaint Lodged") |
| **Resolution** | Whether the caller's issue was resolved, unresolved, or transferred |
| **AI Handled** | Whether the AI successfully managed the call without human intervention |

---

## Enabling ACW on an Assistant

1. Open the assistant and click the **ACW** tab.
2. Toggle **Auto-Run ACW** on.
3. Select the **LLM Model** to use for analysis (defaults to `gpt-4o-mini`).
4. Enable **Call Summary** if you want a prose summary in addition to the score.

ACW runs automatically within a few seconds of every call ending. Results appear in **Call Logs** → call detail view.

---

## Writing a QA Rubric

The **Quality Rubric** is a freeform text field sent to the LLM as scoring instructions. Write it as a numbered list or natural language:

```
Score the AI agent on the following criteria (0-100):

1. Greeting (0-10): Was the caller greeted warmly and professionally?
2. Problem identification (0-20): Did the agent correctly identify the caller's need?
3. Knowledge accuracy (0-30): Were answers factually correct and specific?
4. Efficiency (0-20): Was the call resolved without unnecessary repetition?
5. Closing (0-10): Did the agent confirm resolution and thank the caller?
6. Policy compliance (0-10): Did the agent stay within allowed topics?
```

The LLM will produce a score and brief justification for each criterion.

---

## Disposition Codes

Dispositions are labels applied by the ACW system (or manually by agents) to classify call outcomes.

To manage dispositions:
1. Go to **Assistants** → select your assistant → **Dispositions** tab.
2. Add disposition codes and descriptions.
3. The ACW system will select the best-matching disposition from your list.

---

## Resolution Options

Resolution options are the available values for the "was this resolved?" classification. Default options:

- `resolved` — caller's issue was fully addressed
- `unresolved` — issue not resolved; may need follow-up
- `transferred` — call transferred to a human agent

Customize these in **Assistants** → **Resolution Options** tab.

---

## The `caller_spoke` Tri-State

Botelier tracks whether the caller produced any audio during the call:

| Value | Meaning | Effect on `ai_handled` |
|---|---|---|
| `NULL` | Not yet determined | Treated as eligible (same as `TRUE`) |
| `TRUE` | Caller spoke audio was detected | Normal — AI handled is computed from disposition/resolution |
| `FALSE` | No caller audio detected (silent call) | Call is reclassified to **Unresolved** regardless of other scores |

`caller_spoke = FALSE` typically indicates a dropped call, spam bot, or Twilio test ping. These calls are excluded from AI-handled metrics to avoid inflating resolution rates.

---

## Reading ACW Results

In **Call Logs**, click any call to open the detail view:

- **Transcript** tab — full conversation text with timestamps
- **ACW Summary** tab — QA score breakdown, summary prose, disposition, resolution
- **Events** tab — raw event timeline including when ACW ran

The aggregate QA score appears in the **Call Analytics** dashboard under **AI Handled Rate** and **Avg QA Score** metrics.
