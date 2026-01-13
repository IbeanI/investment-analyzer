from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1. Construct the Database URL
# Format: postgresql://user:password@host:port/database_name
# Note: In a real app, we would read these from os.environ (Environment Variables)
SQLALCHEMY_DATABASE_URL = "postgresql://admin:password123@localhost:5432/investment_portfolio"

# 2. Create the Engine
# This is the actual connection pool to the database
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 3. Create a Session Factory
# Each request will create a new "Session" to interact with the DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 4. Dependency Injection Helper
# This is a Best Practice for FastAPI. It ensures that when a request finishes,
# the database connection is closed, preventing memory leaks.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
