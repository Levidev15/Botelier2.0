---
id: greeting-cache
title: Greeting Cache
sidebar_label: Greeting Cache
---

# Greeting Cache

The **Greeting Cache** pre-generates the assistant's opening audio so it can be delivered to callers in under 100 ms — before the TTS provider has even received the request.

## Why It Exists

The first message a caller hears sets the tone for the entire interaction. Without caching, the first TTS request adds 300–800 ms of silence before the caller hears anything. With caching, the audio is already on disk and begins streaming immediately when the call connects.

## How It Works

1. When you click **Cache Greeting** (or trigger it via the API), Botelier sends the assistant's `first_message` text to the Deepgram TTS API.
2. The returned audio file is stored in `uploads/greeting_cache/` keyed by a hash of the text + voice configuration.
3. On the next incoming call, the voice engine checks for a valid cache entry before initiating the live TTS stream.

:::note Deepgram Only
Greeting caching is currently supported only when the TTS provider is **Deepgram**. Cartesia and other providers stream in real-time without local caching.
:::

---

## Triggering the Cache

### From the UI

On the assistant detail page, click **Cache Greeting**. The button shows the cache status:

- 🟢 **Cached** — audio is ready; shows the cache timestamp
- 🟡 **Stale** — the `first_message` text has changed since caching; click to regenerate
- ⭕ **Not Cached** — no audio on disk yet

### From the Flow Editor

If your flow has an Initial Node with a custom greeting (different from `first_message`), open the node and click **Cache This Greeting** to pre-generate audio for that specific text.

### Via API

```bash
POST /api/assistants/{assistant_id}/cache-greeting?account_id={account_id}

# Optional: override the text to cache
POST /api/assistants/{assistant_id}/cache-greeting?account_id={account_id}&greeting_text=Hello%2C+how+can+I+help+you+today%3F
```

---

## Cache Invalidation

The cache is invalidated when:

- The `first_message` text changes (detected by hash mismatch)
- The `tts_voice` changes
- You manually delete the cache file

Botelier does **not** automatically re-cache on text changes — you must click **Cache Greeting** again. The UI will show the cache as **Stale** when the text no longer matches.

---

## What Happens When the Cache Is Stale

If the cache exists but the text no longer matches, Botelier falls back to a live TTS request for the first message. The caller experiences the normal 300–800 ms delay until you refresh the cache. No error is thrown.

---

## Checking Cache Status

```bash
GET /api/assistants/{assistant_id}/greeting-cache-status?account_id={account_id}

# Response
{
  "cached": true,
  "cached_at": "2025-05-01T10:23:45Z",
  "text_matches_cache": true,
  "outdated": false,
  "supported": true
}
```
