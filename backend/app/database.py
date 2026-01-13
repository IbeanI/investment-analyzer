import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 1. Load environment variables from the .env file
load_dotenv()

# 2. Get the URL from the environment (or crash if it's missing)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# 3. Create the Engine
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 4. Create Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
