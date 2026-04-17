"""
Centralized loguru configuration for the Botelier backend.

Imported once from `main.py` BEFORE any router import so every module's
`from loguru import logger` inherits these sinks.

Why this exists
---------------
Replit's deploy log viewer tags every stderr line as ``[Error]``. Loguru's
default sink writes everything (DEBUG/INFO/WARNING/ERROR) to stderr, so the
prod console becomes a wall of red ``[Error]`` lines for completely routine
activity (every STT chunk, every frame metric, every system-prompt dump).
A real ``Traceback`` becomes invisible.

We solve this with two sinks:

    stdout : levels below WARNING (filtered to suppress noisy pipecat
             debug/info traffic). Replit tags stdout as INFO, so routine
             call activity stops looking like errors.
    stderr : WARNING and above. These are the lines we *want* highlighted —
             "Idle pipeline detected", "RTVIProcessor timed out",
             "VAD stop_secs >= STT p99 latency", real Tracebacks, etc.

Crucially, WARNING+ records from pipecat namespaces are NEVER filtered out.
Those warnings are how we diagnose pipeline issues (Tasks #106, #107).

Env vars
--------
LOG_LEVEL   - Global minimum level for the stdout sink. Default ``INFO``.
              Set to ``DEBUG`` locally to get the per-turn timing markers
              and our own debug payloads. WARNING+ always goes to stderr
              regardless.
LOG_PROMPTS - When ``true``, allows verbose payload dumps (Ava system
              prompt, transfer TwiML XML, etc.) and unmutes noisy pipecat
              debug/info traffic. Default ``false``. Off in production.
"""
import os
import sys
from loguru import logger

# Pipecat namespaces that emit very high-volume DEBUG/INFO traffic on every
# call: per-frame metrics, per-turn full LLM context dump, per-chunk STT,
# per-frame mute/unmute toggles, etc. We silence them below WARNING so the
# production log viewer remains usable. WARNING+ from these same namespaces
# ALWAYS passes through.
_NOISY_PIPECAT_PREFIXES = (
    "pipecat.processors.metrics",
    "pipecat.processors.aggregators",
    "pipecat.processors.frame_processor",
    "pipecat.services.openai",
    "pipecat.services.deepgram",
    "pipecat.services.tts_service",
    "pipecat.services.llm_service",
    "pipecat.adapters",
    "pipecat.audio.turn",
    "pipecat.transports.base_input",
    "pipecat.transports.base_output",
)

_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)

_configured = False


def _truthy(value):
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def should_log_prompts() -> bool:
    """Return True when ``LOG_PROMPTS`` is enabled.

    Use this at call sites that build large payload strings (system prompt
    dump, full TwiML XML dump, etc.) so we don't even pay the f-string
    cost when prompt logging is off.
    """
    return _truthy(os.environ.get("LOG_PROMPTS"))


def _make_stdout_filter(log_prompts):
    """Filter applied to the stdout sink.

    Returns False for WARNING+ (those go to stderr instead — avoids
    duplicate emission). Returns False for noisy pipecat namespaces below
    WARNING unless LOG_PROMPTS is on.
    """
    def _filter(record):
        if record["level"].no >= 30:
            return False
        if log_prompts:
            return True
        name = record.get("name") or ""
        return not any(name.startswith(p) for p in _NOISY_PIPECAT_PREFIXES)
    return _filter


def configure_logging():
    """Install the two-sink loguru config. Idempotent.

    Safe to call from any module's import-time code; subsequent calls are
    no-ops. The first call also emits a single INFO line so operators can
    confirm the new config is live in the deploy logs.
    """
    global _configured
    if _configured:
        return

    log_level = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    log_prompts = should_log_prompts()

    # Drop loguru's default stderr sink so we don't double-log every record.
    logger.remove()

    logger.add(
        sys.stdout,
        level=log_level,
        format=_FORMAT,
        filter=_make_stdout_filter(log_prompts),
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )
    logger.add(
        sys.stderr,
        level="WARNING",
        format=_FORMAT,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )

    _configured = True
    logger.info(
        f"Logging configured: LOG_LEVEL={log_level} "
        f"LOG_PROMPTS={'on' if log_prompts else 'off'}"
    )


# NOTE: deliberately NO module-level `configure_logging()` call.
# `main.py` invokes it explicitly as the very first thing on startup.
# Other modules (e.g. function_mapper.py) only import the pure helper
# `should_log_prompts`, which must NOT have the side-effect of replacing
# whatever loguru sinks tests / scripts / alternate entrypoints have
# already installed.
