#!/bin/bash
# setup_project.sh

# 1. Open your Terminal.
# 2. Make the script executable by running:
# chmod +x setup_project.sh
# 3. Run the script:
# ./setup_project.sh
# Exit immediately if a command exits with a non-zero status
set -e

echo "=================================================="
echo "🚀 INVESTMENT PORTFOLIO ANALYZER - SETUP SCRIPT"
echo "=================================================="

# 1. Check for .env file
if [ ! -f backend/.env ]; then
    echo "⚠️  backend/.env not found. Creating from .env.example..."
    cp backend/.env.example backend/.env
    echo "✅ backend/.env created."
else
    echo "✅ backend/.env found."
fi

# 2. Docker Reset
echo "🛑 Stopping and removing existing containers..."
docker-compose down -v

# 3. Build and Start
echo "🏗️  Building and Starting Containers..."
docker-compose up -d --build

# 4. Wait for Database
echo "⏳ Waiting for Database to be ready..."
# Loop until pg_isready returns 0 (success) inside the db container
until docker-compose exec -T investment_db pg_isready -U user -d investment_db > /dev/null 2>&1; do
    printf "."
    sleep 1
done
echo ""
echo "✅ Database is up and running!"

# 5. Initialize Database Schema
# CHANGED: We use init_db.py to create tables because the baseline migration is empty.
echo "🔄 Initializing Database Schema..."
docker-compose exec -T backend python /app/init_db.py

# CHANGED: We 'stamp' the DB to tell Alembic it is up-to-date, skipping the broken migrations.
echo "🏷️  Stamping Alembic Version..."
docker-compose exec -T backend alembic stamp head
echo "✅ Schema initialized and stamped."

# 6. Run Seed Scripts
echo "🌱 Seeding Sample Data..."

# Copy seed script and run it
docker cp backend/scripts/seed_sample_data.py investment_backend:/app/seed_sample_data.py
docker-compose exec -T backend python /app/seed_sample_data.py

# Run the Proxy Mapping migration (if files exist)
if [ -f backend/scripts/migrate_proxy_mappings.py ]; then
    echo "🗺️  Seeding Proxy Mappings..."
    docker cp backend/scripts/migrate_proxy_mappings.py investment_backend:/app/migrate_proxy_mappings.py
    # Check if the JSON file exists locally before copying
    if [ -f backend/scripts/seed_data/proxy_mappings.json ]; then
        docker cp backend/scripts/seed_data/proxy_mappings.json investment_backend:/app/proxy_mappings.json
        docker-compose exec -T backend python /app/migrate_proxy_mappings.py
    else
        echo "⚠️  proxy_mappings.json not found, skipping proxy seed."
    fi
fi

# 7. Final Status
echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo "Backend API:    http://localhost:8000/docs"
echo "Database:       localhost:5432"
echo "User Email:     demo@example.com"
echo "=================================================="