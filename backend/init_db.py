# backend/init_db.py
from app.models import Base

from app.database import engine

print("Creating database tables...")
# This command looks at all classes inheriting from Base and creates tables for them
Base.metadata.create_all(bind=engine)
print("Tables created successfully!")
