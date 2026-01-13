from app import models
from app.database import get_db
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

app = FastAPI(title="Investment Portfolio Analyzer")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Investment Analyzer API", "status": "operational"}


@app.get("/health/db")
def check_db(db: Session = Depends(get_db)):
    """Health check endpoint to verify database connectivity."""
    users = db.query(models.User).all()
    return {"status": "healthy", "database": "connected", "user_count": len(users)}
