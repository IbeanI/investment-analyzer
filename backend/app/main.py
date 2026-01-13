from app import models, database
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

app = FastAPI(title="Investment Portfolio Analyzer")


# Database Dependency (The "Connector")
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def read_root():
    return {"message": "Welcome to the Investment Analyzer API", "status": "operational"}


@app.get("/check-db")
def check_db(db: Session = Depends(get_db)):
    # This tries to fetch users. If DB is down, this will crash.
    # It proves the full pipeline (API -> Python -> DB) works.
    users = db.query(models.User).all()
    return {"message": "Database connected!", "user_count": len(users)}
