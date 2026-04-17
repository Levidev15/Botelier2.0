"""
Botelier Backend API Server

FastAPI application for managing hotel voice AI assistants.
Provides REST endpoints for tools, integrations, and voice agent configuration.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

# IMPORTANT: configure logging BEFORE any other botelier import so every
# module's `from loguru import logger` inherits the centralised sinks.
# See `botelier/logging_config.py` for the rationale (Task #105).
from botelier.logging_config import configure_logging
configure_logging()

import asyncio
from botelier.database import init_db, SessionLocal, run_stuck_call_sweeper
from botelier.api import tools_router
from botelier.api.phone_numbers import router as phone_numbers_router
from botelier.api.assistants import router as assistants_router
from botelier.api.knowledge_bases import router as knowledge_bases_router, legacy_router as entries_legacy_router
from botelier.api.providers import router as providers_router
from botelier.api.calls import router as calls_router
from botelier.api.call_logs import router as call_logs_router
from botelier.api.websockets import router as websockets_router
from botelier.api.flow_templates import router as flow_templates_router
from botelier.api.simulation import router as simulation_router
from botelier.api.flow_versions import router as flow_versions_router
from botelier.api.admin import router as admin_router
from botelier.api.invitations import router as invitations_router
from botelier.api.auth import router as auth_router
from botelier.api.dispositions import router as dispositions_router
from botelier.api.resolution_options import router as resolution_options_router
from botelier.api.integrations import router as integrations_router
from botelier.api.secrets import router as secrets_router
from botelier.api.tool_sets import router as tool_sets_router
from botelier.api.mcp_connections import router as mcp_connections_router
from botelier.api.api_tester import router as api_tester_router
from botelier.api.sms_pkg import router as sms_router
from botelier.api.sms_compliance import router as sms_compliance_router
from botelier.api.analytics import router as analytics_router
from botelier.api.team import router as team_router
from botelier.api.account import router as account_router

# Initialize FastAPI app
app = FastAPI(
    title="Botelier API",
    description="Backend API for Hotel Voice AI Management",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS configuration for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(admin_router)  # Platform admin endpoints
app.include_router(tools_router)
app.include_router(flow_versions_router)  # Flow versioning endpoints (before tools for route priority)
app.include_router(phone_numbers_router)
app.include_router(assistants_router)
app.include_router(knowledge_bases_router)
app.include_router(entries_legacy_router)  # Legacy /api/entries for backward compatibility
app.include_router(providers_router)
app.include_router(calls_router)
app.include_router(call_logs_router)
app.include_router(websockets_router)
app.include_router(flow_templates_router)
app.include_router(simulation_router)
app.include_router(invitations_router)  # Public invitation endpoints
app.include_router(auth_router)  # Email/password auth endpoints
app.include_router(dispositions_router)  # Assistant dispositions
app.include_router(resolution_options_router)  # Resolution status options
app.include_router(integrations_router)  # Third-party integrations (Opera Cloud, etc.)
app.include_router(secrets_router)  # Account secrets (encrypted API key store)
app.include_router(tool_sets_router)  # Tool collection management
app.include_router(mcp_connections_router)  # MCP server connections for dynamic tools
app.include_router(api_tester_router)  # API testing proxy for tool configuration
app.include_router(sms_router)  # SMS AI conversations
app.include_router(sms_compliance_router)  # SMS A2P 10DLC compliance
app.include_router(analytics_router)  # Analytics dashboards
app.include_router(team_router)  # Account team management
app.include_router(account_router)  # Account-level client endpoints (features, etc.)

uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


@app.on_event("startup")
async def startup_event():
    print("🚀 Initializing Botelier backend...")
    print(f"📊 Database: {os.environ.get('DATABASE_URL', 'Not configured')[:50]}...")
    init_db()
    print("✅ Database initialized")

    from botelier.seeds import seed_all_integrations
    db = SessionLocal()
    try:
        seed_all_integrations(db)
        print("✅ Integration types seeded")

        # One-time idempotent migration: replace invalid Deepgram model names
        # that cause permanent HTTP 400 errors and infinite retry loops.
        # nova-3-phonecall and flux-general-en are not accepted by Deepgram's API.
        from sqlalchemy import text as _text
        _invalid_models = ("nova-3-phonecall", "flux-general-en")
        _fallback = "nova-3-general"
        for _bad in _invalid_models:
            result = db.execute(
                _text(
                    "UPDATE assistants SET stt_model = :good "
                    "WHERE stt_model = :bad"
                ),
                {"good": _fallback, "bad": _bad},
            )
            if result.rowcount:
                print(
                    f"✅ Migrated {result.rowcount} assistant(s) from "
                    f"stt_model='{_bad}' → '{_fallback}'"
                )
        db.commit()
    finally:
        db.close()

    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
        _warmup_vad = SileroVADAnalyzer()
        _warmup_st = LocalSmartTurnAnalyzerV3()
        del _warmup_vad, _warmup_st
        print("✅ Silero VAD and SmartTurn models pre-warmed")
    except Exception as _e:
        print(f"⚠️  Model pre-warm failed (non-fatal): {_e}")

    # Task #96: periodic stuck-call sweeper. Runs immediately at startup
    # and every 5 minutes thereafter, closing any CallLog left in
    # initiated/ringing/in_progress state that has no active pipeline
    # in-process. A finalization_forced CallEvent is emitted per closed row
    # so the Task #97 analytics dashboard can measure leak rate by source.
    # The task is cancelled gracefully in the shutdown_event below.
    from botelier.utils import log_task_exception
    app.state._stuck_call_sweeper_task = asyncio.create_task(_stuck_call_sweeper_loop())
    # Task #116 — surface tracebacks raised outside the loop's internal
    # try/except (e.g. import errors during reload, scheduler failures).
    app.state._stuck_call_sweeper_task.add_done_callback(log_task_exception)
    print("✅ Stuck-call sweeper started (runs every 5 min)")


# Per-call shutdown finalization budget — keeps total deploy block bounded.
_SHUTDOWN_PER_CALL_TIMEOUT = 2.0
_SHUTDOWN_TOTAL_TIMEOUT = 10.0


async def _finalize_active_calls_on_shutdown() -> None:
    """Task #116 — graceful-shutdown finalizer.

    On uvicorn restart (deploy / reload / SIGTERM), in-memory call state
    dies and live WebSockets are torn down. Without this hook, any call
    that was in-progress lingers in the DB as ``in_progress`` for up to
    five minutes until the sweeper's next tick. This pollutes analytics
    and the live-call panel on the dashboard.

    For each active call SID we:

    1. Run ``CallLogger.complete_call(forced_by="shutdown")`` so the row
       reaches a terminal status with a ``finalization_forced`` event
       (``details.source == "shutdown"``) — distinguishable from
       sweeper-closed rows in the leak-rate dashboard.
    2. Cancel the corresponding pipeline so no further frames are pushed
       through a dead transport.

    The whole hook is bounded by ``_SHUTDOWN_TOTAL_TIMEOUT`` so a slow DB
    or a stuck pipeline cancellation cannot block deploys indefinitely.
    """
    try:
        from botelier.api.websockets import call_handler
    except Exception as e:
        print(f"⚠️  shutdown finalizer: could not import call_handler: {e}")
        return

    active_sids = list(
        set(call_handler.active_calls.keys())
        | set(call_handler.call_tasks.keys())
    )
    if not active_sids:
        return

    print(f"🛑 Finalizing {len(active_sids)} active call(s) on shutdown")

    async def _finalize_one(sid: str) -> None:
        # 1. Row finalization (synchronous DB work via to_thread).
        def _do_complete() -> None:
            db = SessionLocal()
            try:
                from botelier.services.call_logger import CallLogger
                CallLogger(db).complete_call(
                    call_sid=sid, forced_by="shutdown"
                )
            finally:
                db.close()

        try:
            await asyncio.wait_for(
                asyncio.to_thread(_do_complete),
                timeout=_SHUTDOWN_PER_CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"⚠️  shutdown finalizer: complete_call timed out for {sid}")
        except Exception as e:
            print(f"⚠️  shutdown finalizer: complete_call failed for {sid}: {e}")

        # 2. Cancel the pipeline so the runner unblocks promptly.
        try:
            await asyncio.wait_for(
                call_handler.cancel_call_pipeline(sid),
                timeout=_SHUTDOWN_PER_CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"⚠️  shutdown finalizer: cancel_call_pipeline timed out for {sid}")
        except Exception as e:
            print(f"⚠️  shutdown finalizer: cancel_call_pipeline failed for {sid}: {e}")

    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[_finalize_one(sid) for sid in active_sids],
                return_exceptions=True,
            ),
            timeout=_SHUTDOWN_TOTAL_TIMEOUT,
        )
        print(f"✅ Shutdown finalizer completed for {len(active_sids)} call(s)")
    except asyncio.TimeoutError:
        print(
            f"⚠️  Shutdown finalizer hit total timeout "
            f"({_SHUTDOWN_TOTAL_TIMEOUT}s) — sweeper will pick up stragglers"
        )


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown: finalize active calls and cancel the stuck-call
    sweeper task so Uvicorn worker exit is clean and no
    asyncio.CancelledError stack trace is logged."""
    # Task #116 — finalize active calls FIRST so they get a "shutdown"
    # finalization_forced event before the sweeper would otherwise close
    # them on next process startup with the less-specific "sweeper" tag.
    try:
        await _finalize_active_calls_on_shutdown()
    except Exception as e:
        print(f"⚠️  shutdown finalizer raised: {e}")

    task = getattr(app.state, "_stuck_call_sweeper_task", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        print("✅ Stuck-call sweeper cancelled on shutdown")


async def _stuck_call_sweeper_loop():
    """Background task: run_stuck_call_sweeper immediately at startup and
    every 5 minutes thereafter, with the set of currently-active call SIDs
    pulled from the singleton CallHandler."""
    _INTERVAL_SECONDS = 300  # 5 minutes
    # Run the first tick immediately so any pre-existing stuck rows from a
    # prior process crash are reclassified before the server has been up for
    # 5 full minutes. Pipeline state is empty at this point, so skip_call_sids
    # is empty — safe because no WebSocket has connected yet.
    first_run = True
    while True:
        try:
            if not first_run:
                await asyncio.sleep(_INTERVAL_SECONDS)
            first_run = False
            try:
                from botelier.api.websockets import call_handler
                active = set(call_handler.active_calls.keys()) | set(call_handler.call_tasks.keys())
            except Exception:
                active = set()
            try:
                await asyncio.to_thread(run_stuck_call_sweeper, active)
            except Exception as _sw_err:
                # Never let a sweeper failure break the loop.
                print(f"⚠️  Stuck-call sweeper tick failed: {_sw_err}")
        except asyncio.CancelledError:
            break
        except Exception as _loop_err:
            # Defensive: log & continue so the loop never silently dies.
            print(f"⚠️  Stuck-call sweeper loop error: {_loop_err}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "botelier-backend",
        "version": "0.1.0"
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Botelier Backend API",
        "docs": "/api/docs",
        "health": "/api/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
