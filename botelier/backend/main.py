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
app.include_router(tools_router)
app.include_router(phone_numbers_router)


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
