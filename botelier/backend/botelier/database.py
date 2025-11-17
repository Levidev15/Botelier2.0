"""
Database configuration for Botelier backend.

Uses SQLAlchemy with PostgreSQL for multi-tenant data persistence.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Get database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=300,    # Recycle connections after 5 minutes
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI routes to get database session.
    
    Usage:
        @app.get("/tools")
        def get_tools(db: Session = Depends(get_db)):
            return db.query(Tool).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.
    Call this once at application startup.
    """
    # Import all models here to ensure they're registered
    from botelier.models import tool  # noqa: F401
    from botelier.models import hotel  # noqa: F401
    from botelier.models import phone_number  # noqa: F401
    
    Base.metadata.create_all(bind=engine)
