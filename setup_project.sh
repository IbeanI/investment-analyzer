#!/bin/bash
# setup_project.sh
#
# Investment Portfolio Analyzer - Complete Setup Script
#
# This script takes you from a cold start to a fully running system.
# After running, you can create portfolios via the Swagger UI at:
#   http://localhost:8000/docs
#
# USAGE:
#   chmod +x setup_project.sh
#   ./setup_project.sh [OPTIONS]
#
# OPTIONS:
#   --fresh     Remove all data and start fresh (destructive!)
#   --no-wait   Skip waiting for services to be ready
#   --help      Show this help message
#
# PREREQUISITES:
#   - Docker and Docker Compose installed
#   - Ports 8000 (API) and 5432 (PostgreSQL) available

set -e  # Exit on error

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
FRESH_START=false
WAIT_FOR_SERVICES=true

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}==================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}==================================================${NC}"
}

print_step() {
    echo -e "${GREEN}[STEP]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

show_help() {
    head -30 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

# =============================================================================
# PARSE ARGUMENTS
# =============================================================================

for arg in "$@"; do
    case $arg in
        --fresh)
            FRESH_START=true
            shift
            ;;
        --no-wait)
            WAIT_FOR_SERVICES=false
            shift
            ;;
        --help|-h)
            show_help
            ;;
        *)
            print_error "Unknown option: $arg"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# =============================================================================
# MAIN SETUP
# =============================================================================

print_header "INVESTMENT PORTFOLIO ANALYZER - SETUP"

# -----------------------------------------------------------------------------
# Step 1: Check Prerequisites
# -----------------------------------------------------------------------------
print_step "Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    echo "  macOS: brew install --cask docker"
    echo "  Or download from: https://www.docker.com/products/docker-desktop"
    exit 1
fi
print_success "Docker installed"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not installed."
    exit 1
fi
print_success "Docker Compose installed"

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi
print_success "Docker daemon running"

# -----------------------------------------------------------------------------
# Step 2: Setup Environment Files
# -----------------------------------------------------------------------------
print_step "Setting up environment files..."

# Root .env (for Docker Compose)
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    print_info "Creating root .env file for Docker (local development defaults)..."
    cat > "$PROJECT_ROOT/.env" << 'EOF'
# Docker Compose Environment Variables (LOCAL DEVELOPMENT ONLY)
# This file is git-ignored. For production, use secure credentials.

POSTGRES_USER=admin
POSTGRES_PASSWORD=localdevpassword
POSTGRES_DB=investment_portfolio

# Optional: For local scripts connecting directly
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
EOF
    print_success "Created $PROJECT_ROOT/.env with local dev defaults"
else
    print_info "Root .env already exists (keeping existing credentials)"
fi

# Backend .env (for application)
if [ ! -f "$BACKEND_DIR/.env" ]; then
    print_info "Creating backend/.env file (local development defaults)..."
    cat > "$BACKEND_DIR/.env" << 'EOF'
# Backend Environment Variables (LOCAL DEVELOPMENT ONLY)
# This file is git-ignored. For production, use secure credentials.

DEBUG=true
LOG_LEVEL=INFO

# Database connection for local development
DATABASE_URL=postgresql://admin:localdevpassword@localhost:5432/investment_portfolio
EOF
    print_success "Created $BACKEND_DIR/.env with local dev defaults"
else
    print_info "Backend .env already exists (keeping existing credentials)"
fi

# -----------------------------------------------------------------------------
# Step 3: Handle Fresh Start (if requested)
# -----------------------------------------------------------------------------
if [ "$FRESH_START" = true ]; then
    print_step "Fresh start requested - removing existing data..."
    print_warn "This will DELETE all database data!"

    # Stop and remove containers
    cd "$PROJECT_ROOT"
    docker-compose down -v 2>/dev/null || true

    # Remove any orphan volumes
    docker volume rm investment-analyzer_postgres_data 2>/dev/null || true

    print_success "Cleaned up existing containers and volumes"
fi

# -----------------------------------------------------------------------------
# Step 4: Build and Start Containers
# -----------------------------------------------------------------------------
print_step "Building and starting Docker containers..."

cd "$PROJECT_ROOT"

# Check if containers are already running
if docker-compose ps --services --filter "status=running" 2>/dev/null | grep -q "backend"; then
    print_info "Containers already running. Restarting..."
    docker-compose restart
else
    print_info "Starting containers (this may take a moment on first run)..."
    docker-compose up -d --build
fi

print_success "Containers started"

# -----------------------------------------------------------------------------
# Step 5: Wait for Database
# -----------------------------------------------------------------------------
if [ "$WAIT_FOR_SERVICES" = true ]; then
    print_step "Waiting for PostgreSQL to be ready..."

    MAX_RETRIES=30
    RETRY_COUNT=0

    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if docker-compose exec -T investment_db pg_isready -U admin -d investment_portfolio > /dev/null 2>&1; then
            print_success "PostgreSQL is ready"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        printf "."
        sleep 1
    done
    echo ""

    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        print_error "PostgreSQL failed to start. Check logs with: docker-compose logs investment_db"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Step 6: Initialize Database Schema
# -----------------------------------------------------------------------------
print_step "Initializing database schema..."

# Run init_db.py to create tables
docker-compose exec -T backend python /app/init_db.py

# Stamp Alembic to mark current state as migrated
docker-compose exec -T backend alembic stamp head 2>/dev/null || true

print_success "Database schema initialized"

# -----------------------------------------------------------------------------
# Step 7: Wait for API to be Ready
# -----------------------------------------------------------------------------
if [ "$WAIT_FOR_SERVICES" = true ]; then
    print_step "Waiting for API to be ready..."

    MAX_RETRIES=30
    RETRY_COUNT=0

    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/docs" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            print_success "API is ready"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        printf "."
        sleep 1
    done
    echo ""

    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        print_warn "API may not be ready yet. Check logs with: docker-compose logs backend"
    fi
fi

# -----------------------------------------------------------------------------
# Step 8: Verify Services
# -----------------------------------------------------------------------------
print_step "Verifying services..."

# Test API health
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/docs" 2>/dev/null || echo "000")
if [ "$API_STATUS" = "200" ]; then
    print_success "API: Running (http://localhost:8000)"
else
    print_warn "API: May still be starting (HTTP $API_STATUS)"
fi

# Test Database connection via API
DB_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/portfolios" 2>/dev/null || echo "000")
if [ "$DB_STATUS" = "200" ]; then
    print_success "Database: Connected"
else
    print_warn "Database: Connection may still be initializing"
fi

# -----------------------------------------------------------------------------
# Step 9: Seed Test User
# -----------------------------------------------------------------------------
print_step "Seeding test user..."

docker-compose exec -T investment_db psql -U admin -d investment_portfolio -c "
INSERT INTO users (email, hashed_password, created_at, updated_at)
VALUES ('test_user@test.com', 'test_password', NOW(), NOW())
ON CONFLICT (email) DO NOTHING;"

print_success "Test user 'test_user@test.com' created (or already exists)"


# =============================================================================
# FINAL OUTPUT
# =============================================================================

print_header "SETUP COMPLETE!"

echo ""
echo -e "${GREEN}Your Investment Portfolio Analyzer is ready!${NC}"
echo ""
echo "ACCESS POINTS:"
echo "  Swagger UI:  http://localhost:8000/docs"
echo "  ReDoc:       http://localhost:8000/redoc"
echo "  PostgreSQL:  localhost:5432 (admin/password123)"
echo ""
echo "GETTING STARTED:"
echo "  1. Open Swagger UI: http://localhost:8000/docs"
echo "  2. Create a portfolio: POST /portfolios"
echo "  3. Add transactions: POST /portfolios/{id}/transactions"
echo "  4. Sync market data: POST /portfolios/{id}/sync"
echo "  5. View valuation: GET /portfolios/{id}/valuation"
echo ""
echo "COMMON COMMANDS:"
echo "  View logs:        docker-compose logs -f backend"
echo "  Run tests:        docker-compose exec backend pytest"
echo "  Stop services:    docker-compose down"
echo "  Fresh restart:    ./setup_project.sh --fresh"
echo ""
echo "API ENDPOINTS:"
echo "  Portfolios:       /portfolios"
echo "  Transactions:     /portfolios/{id}/transactions"
echo "  Sync Data:        /portfolios/{id}/sync"
echo "  Valuation:        /portfolios/{id}/valuation"
echo "  History:          /portfolios/{id}/valuation/history"
echo "  Analytics:        /portfolios/{id}/analytics"
echo ""
