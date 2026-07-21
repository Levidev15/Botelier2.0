---
name: src/pipecat fork resolution & Flux turn strategies
description: Why dev and prod run different pipecat code, and why Flux paths must never pass user_turn_strategies=None
---

# src/pipecat fork resolution differs dev vs prod

**Rule:** Production Docker sets `PYTHONPATH=/app/src`, so `src/pipecat/` (the local fork) shadows pip's `pipecat-ai`. Dev (Replit workflow) has NO such override — dev imports the pip package and never exercises fork changes.

**Why:** A production-only outage (all voice calls crashing in 2-3s) was invisible in dev for two stacked reasons: dev ran unforked pip code AND happened to have `transformers` installed while the Docker image did not.

**How to apply:**
- Any test of `src/pipecat/` changes must run with `PYTHONPATH=<repo>/src` and assert `pipecat.__file__` points into `workspace/src`, or you're silently testing the pip package.
- Any import added inside `src/pipecat/` or `botelier/backend/` must exist in `botelier/backend/requirements.txt` — dev's ambient site-packages prove nothing about the Docker image.

# Flux turn strategies must be explicit, never None

**Rule:** On the Deepgram Flux STT path, always pass explicit turn strategies to `LLMUserAggregatorParams`. Interruptions enabled → `ExternalUserTurnStrategies()`. Interruptions disabled → `UserTurnStrategies(start=[TranscriptionUserTurnStartStrategy(enable_interruptions=False)], stop=[ExternalUserTurnStopStrategy()])`.

**Why:** `user_turn_strategies=None` makes the aggregator build the default `UserTurnStrategies()`, whose `__post_init__` constructs a SmartTurn stop strategy (`LocalSmartTurnAnalyzerV3` → `from transformers import WhisperFeatureExtractor`) — a hard per-call crash if transformers is absent, and a silently-attached ML turn model Flux never needed. Upstream pipecat's own Flux examples pair Flux with `ExternalUserTurnStrategies()`.

**How to apply:**
- Flux drives everything itself: StartOfTurn → broadcasts `UserStartedSpeakingFrame` + `broadcast_interruption()` (gated by `should_interrupt`, wired to the assistant's interruption toggle); EndOfTurn → broadcasts `UserStoppedSpeakingFrame`. `ExternalUserTurnStartStrategy(enable_interruptions=False)` is correct — Flux owns interruption, not the strategy.
- The fork's `default_user_turn_stop_strategies()` now fail-softs to `[]` with a warning if SmartTurn deps are missing — defense-in-depth only; no Botelier path should rely on it.
- SmartTurn v3 is ONNX (bundled .onnx model, no torch, no HF download); transformers is needed only for `WhisperFeatureExtractor` (numpy-only preprocessing).

# Do NOT add transformers to the production image without a build test

**Rule:** Adding `transformers` (5.x) to `botelier/backend/requirements.txt` coincided with the Azure voice container entering a startup crash-loop (startup probe exit 1, uvicorn dead before binding). SUSPECTED cause — never confirmed from build/boot logs (Azure logs were unreachable): a fresh `pip install` in `python:3.11-slim` resolving transformers 5.x's transitive deps (`typer`→`click`, `tokenizers`, `huggingface-hub`) breaks the from-scratch image even though dev's incremental site-packages work fine. Confirm the actual failure in a clean-venv/Docker build before trusting this specific story; if a revision without transformers still crash-loops, pivot to Azure-side suspects (image pull, env, Key Vault at boot).

**Why:** Dev never reproduces the Docker resolver: dev installs incrementally into an environment with existing pins; the image resolves everything from scratch. `pip check` passing in dev proves nothing about the image.

**How to apply:**
- Before adding any heavy/transitive-rich dependency to requirements.txt, build the production Dockerfile (or a pip install into a clean venv from only requirements.txt) and boot-test it first.
- The Silero-VAD path constructs `LocalSmartTurnAnalyzerV3` unconditionally when VAD is enabled (lazy method-scope import) — with transformers absent from the image those calls fail per-call; only the Flux path is transformers-free by design. Fail-softing that construction or safely reintroducing transformers is open work.
