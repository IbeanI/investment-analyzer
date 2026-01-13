from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db

app = FastAPI(title="Investment Portfolio Analyzer")


@app.get("/")
def read_root() -> dict[str, str]:
    """Root endpoint returning API status."""
    return {"message": "Welcome to the Investment Analyzer API", "status": "operational"}


@app.get("/health/db")
def check_db(db: Session = Depends(get_db)) -> dict[str, str]:
    """Health check endpoint to verify database connectivity."""
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}
