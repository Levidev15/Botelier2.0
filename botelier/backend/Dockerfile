# ── Stage 1: builder ─────────────────────────────────────────────────────────
# Install all Python dependencies (some require gcc to compile C extensions).
# The compiled site-packages are then copied to the slim runtime image.
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY botelier/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
# Lean production image — only what's needed to run.
FROM python:3.11-slim

WORKDIR /app

# libgomp1  — OpenMP runtime required by PyTorch (SileroVAD / SmartTurn models)
# ca-certificates — needed for HTTPS calls to Deepgram, OpenAI, Twilio, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Python packages from builder ─────────────────────────────────────────────
COPY --from=builder /install /usr/local

# ── Local Pipecat source ──────────────────────────────────────────────────────
# This directory overrides the pip-installed pipecat-ai, exactly as in dev.
# Must sit on PYTHONPATH before site-packages so imports resolve here first.
COPY src/ ./src/
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# ── Application code ──────────────────────────────────────────────────────────
COPY botelier/backend/ .

# Greeting audio cache directory.
# In production: mount an Azure Files share here so cached greetings survive
# container restarts. Without a mount the directory is ephemeral — greetings
# are re-generated on the first call after a restart (~1-2 s latency hit).
RUN mkdir -p uploads/greeting_cache uploads/mms

# ── Security: non-root user ───────────────────────────────────────────────────
RUN useradd -m -u 1000 botelier && chown -R botelier:botelier /app
USER botelier

EXPOSE 8000

# ── Startup ───────────────────────────────────────────────────────────────────
# --timeout-keep-alive 75  keeps idle HTTP connections alive past Twilio's
#                          60 s status-callback interval.
# No --reload flag — live voice calls use persistent WebSocket connections that
# must not be torn down on code change (same reason as the Replit workflow).
# SileroVAD + SmartTurn model weights are downloaded on first startup by the
# pre-warm step in startup_event (main.py). With min-replicas=1 this only
# happens once per deployment, not on every call.
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--log-level", "info", \
     "--timeout-keep-alive", "75"]
