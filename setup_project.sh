#!/bin/bash
# setup_project.sh
#
# Investment Portfolio Analyzer - Complete Setup Script
#
# Usage:
#   1. Open your Terminal.
#   2. Make the script executable by running:
#      chmod +x setup_project.sh
#   3. Run the script:
#      ./setup_project.sh
#
# This script will:
#   - Create .env file if missing
#   - Reset Docker containers
#   - Initialize database schema
#   - Seed sample data
#   - Sync market data
#   - Verify all services are working

# Exit immediately if a command exits with a non-zero status
set -e

echo "=================================================="
echo "🚀 INVESTMENT PORTFOLIO ANALYZER - SETUP SCRIPT"
echo "   Phase 1-5 Complete (Foundation → Analytics)"
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
echo ""
echo "🛑 Stopping and removing existing containers..."
docker-compose down -v

# 3. Build and Start
echo ""
echo "🏗️  Building and Starting Containers..."
docker-compose up -d --build

# 4. Wait for Database
echo ""
echo "⏳ Waiting for Database to be ready..."
until docker-compose exec -T investment_db pg_isready -U user -d investment_db > /dev/null 2>&1; do
    printf "."
    sleep 1
done
echo ""
echo "✅ Database is up and running!"

# 5. Initialize Database Schema
echo ""
echo "🔄 Initializing Database Schema..."
docker-compose exec -T backend python /app/init_db.py

echo "🏷️  Stamping Alembic Version..."
docker-compose exec -T backend alembic stamp head
echo "✅ Schema initialized and stamped."

# 6. Run Seed Scripts
echo ""
echo "🌱 Seeding Sample Data..."
docker-compose exec -T backend python /app/scripts/seed_sample_data.py

# 7. Run Proxy Mappings and Setup
echo ""
echo "🗺️  Setting up Proxy Backcasting..."
if [ -f backend/scripts/migrate_proxy_mappings.py ]; then
    docker-compose exec -T backend python -m scripts.migrate_proxy_mappings || true
fi

# 8. Sync Market Data for Sample Portfolio
echo ""
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

# 9. Verify Services (Quick Health Check)
echo ""
echo "🔍 Verifying Services..."

# Test valuation endpoint
VALUATION_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/portfolios/1/valuation")
if [ "$VALUATION_STATUS" = "200" ]; then
    echo "✅ Valuation Service: Working"
else
    echo "⚠️  Valuation Service: HTTP $VALUATION_STATUS"
fi

# Test analytics endpoint (new in Phase 5)
ANALYTICS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/portfolios/1/analytics?from_date=2024-01-01&to_date=2024-12-31")
if [ "$ANALYTICS_STATUS" = "200" ]; then
    echo "✅ Analytics Service: Working"
else
    echo "⚠️  Analytics Service: HTTP $ANALYTICS_STATUS"
fi

# 10. Final Status
echo ""
echo "=================================================="
echo "🎉 SETUP COMPLETE!"
echo "=================================================="
echo ""
echo "📍 Access Points:"
echo "   API Documentation: http://localhost:8000/docs"
echo "   Database:          localhost:5432"
echo "   Demo User:         demo@example.com"
echo ""
echo "📊 VALUATION ENDPOINTS (Phase 4):"
echo "   GET /portfolios/1/valuation"
echo "   GET /portfolios/1/valuation/history?from_date=2024-01-01&to_date=2024-12-31&interval=monthly"
echo ""
echo "📈 ANALYTICS ENDPOINTS (Phase 5):"
echo "   GET /portfolios/1/analytics?from_date=2024-01-01&to_date=2024-12-31"
echo "   GET /portfolios/1/analytics?from_date=2024-01-01&to_date=2024-12-31&benchmark=^SPX"
echo "   GET /portfolios/1/analytics/performance?from_date=2024-01-01&to_date=2024-12-31"
echo "   GET /portfolios/1/analytics/risk?from_date=2024-01-01&to_date=2024-12-31"
echo "   GET /portfolios/1/analytics/benchmark?from_date=2024-01-01&to_date=2024-12-31&benchmark=^SPX"
echo ""
echo "🧪 RUN TESTS:"
echo "   docker-compose exec backend pytest"
echo "   docker-compose exec backend pytest tests/services/analytics/ -v"
echo ""
echo "📋 VIEW LOGS:"
echo "   docker-compose logs -f backend"
echo ""
echo "=================================================="