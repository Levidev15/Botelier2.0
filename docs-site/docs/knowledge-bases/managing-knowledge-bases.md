---
id: managing-knowledge-bases
title: Managing Knowledge Bases
sidebar_label: Managing Knowledge Bases
---

# Managing Knowledge Bases

A **Knowledge Base** is a collection of question-and-answer entries that the assistant uses to respond to caller questions. During a call, the assistant performs a semantic search over the KB and includes relevant entries in its context window.

## Creating a Knowledge Base

1. Go to **Knowledge Base** in the left sidebar.
2. Click **New Knowledge Base**.
3. Enter a **Name** (required) and optional **Description**.
4. Click **Create**.

---

## Adding Entries Manually

1. Open the knowledge base.
2. Click **+ Add Entry**.
3. Fill in:
   - **Question** — a natural-language question a caller might ask
   - **Answer** — a complete spoken-language response (avoid markdown, bullet lists, or HTML)
   - **Category** — optional label for filtering and organization
   - **Expiration Date** — optional date after which the entry is excluded from queries

4. Click **Save Entry**.

:::tip Writing Good Q&A Pairs
- Write questions as a caller would actually say them: "What time do you close?" not "Business hours query"
- Write answers as complete spoken sentences: "We close at 6 PM on weekdays and 4 PM on Saturdays." not just "6 PM weekdays, 4 PM Saturday"
- One topic per entry — don't combine unrelated facts
:::

---

## Bulk CSV Import

Download the CSV template from the KB page (click **Import → Download Template**). The template has four columns:

| Column | Required | Description |
|---|---|---|
| `question` | Yes | The caller's question |
| `answer` | Yes | The spoken response |
| `category` | No | Optional label |
| `expiration_date` | No | ISO 8601 date (YYYY-MM-DD) |

To import:
1. Click **Import → From CSV**.
2. Select your CSV file.
3. Review the preview and click **Import**.

Entries are added without replacing existing ones. Duplicate questions are allowed.

---

## URL Import (Website Crawl)

Botelier can crawl a website and automatically generate Q&A pairs using an LLM.

1. Click **Import → From URL**.
2. Enter the starting URL (must be `http://` or `https://`).
3. Set **Max Pages** (1–20; default 10).
4. Optionally set a **Category** tag for the imported entries.
5. Click **Import**.

The crawler fetches pages in BFS order within the same domain, extracts meaningful text, and calls OpenAI to generate Q&A pairs. Pages behind authentication or requiring JavaScript rendering may not be crawlable.

**What gets crawled:** Text content of HTML pages — navigation, footers, scripts, and cookies banners are stripped before LLM processing.

**Update behavior:** URL import always adds new entries. It does not detect or update previously imported entries from the same URL. Re-importing will create duplicates; delete old entries first if needed.

---

## CSV Export

To export all entries:
1. Click **Export → CSV**.
2. The file downloads with all four columns populated.

---

## Bulk Delete

1. Check the checkboxes next to entries you want to delete.
2. Click **Delete Selected**.
3. Confirm the deletion.

To delete all entries in a category, filter by category first, then select all.

---

## Attaching a KB to an Assistant

A knowledge base must be attached to an assistant to be active. Each assistant supports one KB.

1. Open the assistant.
2. Under **Knowledge Base**, select your KB from the dropdown.
3. Click **Save**.

---

## Character and Token Limits

| Limit | Value |
|---|---|
| Maximum question length | 500 characters |
| Maximum answer length | 2,000 characters |
| Maximum entries per KB | No hard limit (performance degrades above ~5,000 entries) |

**Chunking:** For retrieval, each entry's question and answer are indexed together as a single chunk. Long answers are not split further — keep answers concise for best retrieval accuracy.

---

## Deleting a Knowledge Base

Deleting a KB also deletes all its entries and removes it from any assigned assistants. This action is irreversible.

1. Open the KB.
2. Click **Delete Knowledge Base** in the danger zone.
3. Confirm.
