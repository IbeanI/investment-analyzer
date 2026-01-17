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
# --build ensures your latest local scripts are copied into the container image
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
echo "🔄 Initializing Database Schema..."
docker-compose exec -T backend python /app/init_db.py

echo "🏷️  Stamping Alembic Version..."
docker-compose exec -T backend alembic stamp head
echo "✅ Schema initialized and stamped."

# 6. Run Seed Scripts
echo "🌱 Seeding Sample Data..."

# CHANGED: We run the script directly from the container image.
# No need to 'docker cp' because 'docker-compose build' already put it there.
docker-compose exec -T backend python /app/scripts/seed_sample_data.py

# 7. Run Migrations / Proxy Setup
# We check locally if the file exists just to be safe, but run it inside Docker.
if [ -f backend/scripts/migrate_proxy_mappings.py ]; then
    echo "🗺️  Seeding Proxy Mappings..."
    # CHANGED: We run as a module (-m) from /app so relative imports works
    # and it can find 'scripts/seed_data/proxy_mappings.json' correctly.
    docker-compose exec -T backend python -m scripts.migrate_proxy_mappings
fi

# 8. Final Status
echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo "Backend API:    http://localhost:8000/docs"
echo "Database:       localhost:5432"
echo "User Email:     demo@example.com"
echo "=================================================="