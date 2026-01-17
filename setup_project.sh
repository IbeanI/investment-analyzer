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
docker-compose exec -T backend python /app/scripts/seed_sample_data.py

# 7. Run Proxy Mappings (if exists)
if [ -f backend/scripts/migrate_proxy_mappings.py ]; then
    echo "🗺️  Seeding Proxy Mappings..."
    docker-compose exec -T backend python -m scripts.migrate_proxy_mappings
fi

# 8. NEW: Sync Market Data for Sample Portfolio
echo "📈 Syncing Market Data (this may take 30-60 seconds)..."
# Wait for backend to be fully ready
sleep 5

# Sync portfolio 1 (the demo portfolio)
curl -s -X POST "http://localhost:8000/portfolios/1/sync" \
    -H "Content-Type: application/json" \
    -d '{"force_refresh": false}' | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if data.get('success'):
        print(f\"✅ Market data synced: {data.get('prices_fetched', 0)} prices, {data.get('fx_rates_fetched', 0)} FX rates\")
    else:
        print(f\"⚠️  Sync completed with warnings: {data.get('warnings', [])}\")
except:
    print('⚠️  Could not parse sync response (API may still be starting)')
"

# 9. Final Status
echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo "Backend API:    http://localhost:8000/docs"
echo "Database:       localhost:5432"
echo "User Email:     demo@example.com"
echo ""
echo "📊 Try these endpoints:"
echo "   GET  /portfolios/1/valuation"
echo "   GET  /portfolios/1/valuation/history?from_date=2024-01-01&to_date=2024-12-31&interval=monthly"
echo "=================================================="