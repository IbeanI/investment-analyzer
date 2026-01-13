#!/usr/bin/env python3
# backend/init_db.py
"""
Database initialization script.

This script can be run from any directory:
    python backend/init_db.py
    cd backend && python init_db.py
"""
import sys
from pathlib import Path

# Add the backend directory to Python path so 'app' package is importable
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database import engine
from app.models import Base


def init_db() -> None:
    """Create all database tables defined in models."""
    print("Creating database tables...")
    # This command looks at all classes inheriting from Base and creates tables for them
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")


if __name__ == "__main__":
    init_db()
