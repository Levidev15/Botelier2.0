"""
Botelier Backend API Server

FastAPI application for managing hotel voice AI assistants.
Provides REST endpoints for tools, integrations, and voice agent configuration.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from botelier.database import init_db
from botelier.api import tools_router
from botelier.api.phone_numbers import router as phone_numbers_router
from botelier.api.assistants import router as assistants_router
from botelier.api.knowledge_bases import router as entries_router
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
app.include_router(entries_router)
app.include_router(providers_router)
app.include_router(calls_router)
app.include_router(call_logs_router)
app.include_router(websockets_router)
app.include_router(flow_templates_router)
app.include_router(simulation_router)
app.include_router(invitations_router)  # Public invitation endpoints
app.include_router(auth_router)  # Email/password auth endpoints
app.include_router(dispositions_router)  # Assistant dispositions


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    print("🚀 Initializing Botelier backend...")
    print(f"📊 Database: {os.environ.get('DATABASE_URL', 'Not configured')[:50]}...")
    init_db()
    print("✅ Database initialized")


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
