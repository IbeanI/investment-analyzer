# backend/app/database.py
"""
Database connection and session management.

This module configures SQLAlchemy with:
- Connection pooling for production performance
- Environment-aware settings (test vs production)
- Health check capabilities

Pool Configuration (configurable via environment variables):
- DB_POOL_SIZE: Persistent connections (default: 5)
- DB_POOL_MAX_OVERFLOW: Burst capacity (default: 10)
- DB_POOL_RECYCLE: Connection lifetime (default: 3600s)
- DB_POOL_PRE_PING: Health checks (default: True)
"""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool, QueuePool

from .config import settings

logger = logging.getLogger(__name__)


def _create_engine():
    """
    Create SQLAlchemy engine with environment-appropriate configuration.

    Returns:
        Engine: Configured SQLAlchemy engine

    Configuration varies by database type:
    - SQLite (test only): Uses StaticPool for in-memory database sharing
    - PostgreSQL: Uses QueuePool with configurable connection pooling
    """
    if settings.is_sqlite:
        # SQLite configuration (test environment only)
        # StaticPool keeps a single connection for in-memory SQLite
        # check_same_thread=False required for FastAPI's async context
        logger.info("Configuring SQLite database (test mode)")
        return create_engine(
            settings.database_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
            echo=settings.debug,
        )

    # PostgreSQL configuration with connection pooling
    logger.info(
        f"Configuring PostgreSQL database pool: "
        f"size={settings.db_pool_size}, "
        f"max_overflow={settings.db_pool_max_overflow}, "
        f"recycle={settings.db_pool_recycle}s, "
        f"pre_ping={settings.db_pool_pre_ping}"
    )

    return create_engine(
        settings.database_url,
        poolclass=QueuePool,
        # Core pool settings
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        # Connection health and lifecycle
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
        # Timeout waiting for connection from pool (seconds)
        pool_timeout=30,
        # Echo SQL for debugging (controlled by DEBUG setting)
        echo=settings.debug,
    )


# Create engine and session factory
engine = _create_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency that provides a database session.

    Yields:
        Session: A SQLAlchemy database session that auto-closes after use.

    Usage:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> dict:
    """
    Check database connectivity and pool status.

    Returns:
        dict: Health status with connection info

    Used by health check endpoints to verify database availability.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.commit()

        pool_status = {
            "pool_size": engine.pool.size(),
            "checked_in": engine.pool.checkedin(),
            "checked_out": engine.pool.checkedout(),
            "overflow": engine.pool.overflow(),
        }

        return {
            "status": "healthy",
            "database": "postgresql" if not settings.is_sqlite else "sqlite",
            "pool": pool_status,
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
