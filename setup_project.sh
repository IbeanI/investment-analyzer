#!/bin/bash
# setup_project.sh
#
# Investment Portfolio Analyzer - Complete Setup Script
#
# This script takes you from a cold start to a fully running system.
# After running, you can create portfolios via the Swagger UI at:
#   http://localhost:8000/docs
#
# ============================================================================
# SECURITY WARNING - LOCAL DEVELOPMENT ONLY
# ============================================================================
# This script creates default credentials for local development convenience.
# These credentials are NOT SECURE and must NEVER be used in production.
#
# For production deployments:
#   - Use a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
#   - Generate strong, unique passwords
#   - Never commit credentials to version control
#   - Use environment-specific configuration
# ============================================================================
#
# USAGE:
#   chmod +x setup_project.sh
#   ./setup_project.sh [OPTIONS]
#
# OPTIONS:
#   --fresh        Remove all data and start fresh (destructive!)
#   --no-wait      Skip waiting for services to be ready
#   --no-frontend  Skip frontend setup
#   --help         Show this help message
#
# PREREQUISITES:
#   - Docker and Docker Compose installed
#   - Node.js 18+ and npm installed (for frontend)
#   - Ports 8000 (API), 5432 (PostgreSQL), and 3000 (Frontend) available

set -e  # Exit on error

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
FRESH_START=false
WAIT_FOR_SERVICES=true
SETUP_FRONTEND=true

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
        --no-frontend)
            SETUP_FRONTEND=false
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

# Check Docker Compose and determine which command to use
DOCKER_COMPOSE=""
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    print_error "Docker Compose is not installed."
    exit 1
fi
print_success "Docker Compose installed (using '$DOCKER_COMPOSE')"

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi
print_success "Docker daemon running"

# Check curl (used for health checks)
if ! command -v curl &> /dev/null; then
    print_error "curl is not installed. Please install curl first."
    exit 1
fi
print_success "curl installed"

# Check Node.js (for frontend)
if [ "$SETUP_FRONTEND" = true ]; then
    if ! command -v node &> /dev/null; then
        print_error "Node.js is not installed. Please install Node.js 18+ first."
        echo "  macOS: brew install node"
        echo "  Or download from: https://nodejs.org/"
        exit 1
    fi
    NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$NODE_VERSION" -lt 18 ]; then
        print_error "Node.js 18+ required (found v$NODE_VERSION)"
        exit 1
    fi
    print_success "Node.js $(node -v) installed"

    if ! command -v npm &> /dev/null; then
        print_error "npm is not installed."
        exit 1
    fi
    print_success "npm $(npm -v) installed"
fi

# -----------------------------------------------------------------------------
# Step 2: Setup Environment Files
# -----------------------------------------------------------------------------
print_step "Setting up environment files..."

# Single .env at project root (for both Docker Compose and FastAPI app)
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    print_info "Creating .env file (local development defaults)..."
    cat > "$PROJECT_ROOT/.env" << 'EOF'
# Investment Portfolio Analyzer - Environment Variables
# =====================================================================
# SECURITY WARNING: This file contains credentials!
# - This file is for LOCAL DEVELOPMENT ONLY
# - NEVER commit this file to version control (it's in .gitignore)
# - NEVER use these credentials in production
# - For production: use secrets management (AWS Secrets Manager, Vault, etc.)
# =====================================================================
#
# Single .env for both Docker Compose and FastAPI app.

# =============================================================================
# PostgreSQL Container (used by Docker Compose)
# CHANGE THESE VALUES for any non-local environment!
# =============================================================================
POSTGRES_USER=admin
POSTGRES_PASSWORD=localdevpassword
POSTGRES_DB=investment_portfolio
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# =============================================================================
# Application Settings (used by FastAPI)
# =============================================================================
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Database connection for the app
# Note: Use 'localhost' for local dev, 'investment_db' inside Docker network
DATABASE_URL=postgresql://admin:localdevpassword@localhost:5432/investment_portfolio

# =============================================================================
# Authentication (JWT)
# =============================================================================
JWT_SECRET_KEY=dev-secret-key-change-in-production-32chars

# =============================================================================
# Email (Optional - without these, verification emails are logged to console)
# =============================================================================
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your-email@gmail.com
# SMTP_PASSWORD=your-app-password
# SMTP_FROM_EMAIL=your-email@gmail.com

# =============================================================================
# Google OAuth (Optional)
# =============================================================================
# GOOGLE_CLIENT_ID=your-google-client-id
# GOOGLE_CLIENT_SECRET=your-google-client-secret
# GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# =============================================================================
# Frontend URL (for email links)
# =============================================================================
FRONTEND_URL=http://localhost:3000
EOF
    print_success "Created $PROJECT_ROOT/.env with local dev defaults"
else
    print_info ".env already exists (keeping existing configuration)"
fi

# -----------------------------------------------------------------------------
# Step 3: Handle Fresh Start (if requested)
# -----------------------------------------------------------------------------
if [ "$FRESH_START" = true ]; then
    print_step "Fresh start requested - removing existing data..."
    print_warn "This will DELETE all database data!"

    # Stop and remove containers
    cd "$PROJECT_ROOT"
    $DOCKER_COMPOSE down -v 2>/dev/null || true

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
if $DOCKER_COMPOSE ps --services --filter "status=running" 2>/dev/null | grep -q "backend"; then
    print_info "Containers already running. Restarting..."
    $DOCKER_COMPOSE restart
else
    print_info "Starting containers (this may take a moment on first run)..."
    $DOCKER_COMPOSE up -d --build
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
        if $DOCKER_COMPOSE exec -T investment_db pg_isready -U admin -d investment_portfolio > /dev/null 2>&1; then
            print_success "PostgreSQL is ready"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        printf "."
        sleep 1
    done
    echo ""

    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        print_error "PostgreSQL failed to start. Check logs with: $DOCKER_COMPOSE logs investment_db"
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Step 6: Initialize Database Schema
# -----------------------------------------------------------------------------
print_step "Initializing database schema..."

# Run init_db.py to create tables
$DOCKER_COMPOSE exec -T backend python /app/init_db.py

# Stamp Alembic to mark current state as migrated
$DOCKER_COMPOSE exec -T backend alembic stamp head 2>/dev/null || true

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
        print_warn "API may not be ready yet. Check logs with: $DOCKER_COMPOSE logs backend"
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

# Test Database connection via API health endpoint
DB_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/health" 2>/dev/null || echo "000")
if [ "$DB_STATUS" = "200" ]; then
    print_success "Database: Connected"
else
    print_warn "Database: Connection may still be initializing"
fi

# -----------------------------------------------------------------------------
# Step 9: Seed Test User (LOCAL DEVELOPMENT ONLY)
# -----------------------------------------------------------------------------
print_step "Seeding test user (dev only)..."

# WARNING: This creates a user with a real bcrypt hash for password "password123".
# This is for LOCAL DEVELOPMENT convenience only.
# In production, users should be created through proper registration flows.
# Hash generated with: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('password123'))"
$DOCKER_COMPOSE exec -T investment_db psql -U admin -d investment_portfolio -c "
INSERT INTO users (email, hashed_password, is_email_verified, is_active, created_at, updated_at)
VALUES ('test@example.com', '\$2b\$12\$D1YpH7zZtP9nXP89zArmIec/QClo0ojAYakC4iaY4xtQZIv4VS7ta', true, true, NOW(), NOW())
ON CONFLICT (email) DO NOTHING;"

print_success "Test user created: test@example.com / password123"

# -----------------------------------------------------------------------------
# Step 10: Setup Frontend
# -----------------------------------------------------------------------------
if [ "$SETUP_FRONTEND" = true ]; then
    print_step "Setting up frontend..."

    cd "$FRONTEND_DIR"

    # Install dependencies
    print_info "Installing frontend dependencies..."
    npm install --silent

    print_success "Frontend dependencies installed"

    # Create frontend .env.local if it doesn't exist
    if [ ! -f "$FRONTEND_DIR/.env.local" ]; then
        print_info "Creating frontend .env.local..."
        cat > "$FRONTEND_DIR/.env.local" << 'EOF'
# Frontend Environment Variables
# This file is for local development only

NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
        print_success "Created frontend .env.local"
    else
        print_info "Frontend .env.local already exists"
    fi

    cd "$PROJECT_ROOT"
fi

# =============================================================================
# FINAL OUTPUT
# =============================================================================

print_header "SETUP COMPLETE!"

echo ""
echo -e "${GREEN}Your Investment Portfolio Analyzer is ready!${NC}"
echo ""
echo "ACCESS POINTS:"
echo "  Frontend:    http://localhost:3000 (run 'npm run dev' in frontend/)"
echo "  Swagger UI:  http://localhost:8000/docs"
echo "  ReDoc:       http://localhost:8000/redoc"
echo "  PostgreSQL:  localhost:5432 (see .env for credentials)"
echo ""
echo "TEST USER (dev only):"
echo "  Email:     test@example.com"
echo "  Password:  password123"
echo ""
echo "GETTING STARTED:"
if [ "$SETUP_FRONTEND" = true ]; then
echo "  1. Start frontend: cd frontend && npm run dev"
echo "  2. Open browser:   http://localhost:3000"
echo "  3. Login with test credentials above"
echo "  4. Create a portfolio and start tracking!"
echo ""
echo "  Or use the API directly via Swagger UI:"
fi
echo "  1. Open Swagger UI: http://localhost:8000/docs"
echo "  2. Login: POST /auth/login with test credentials above"
echo "  3. Copy the access_token from response"
echo "  4. Click 'Authorize' button, paste: Bearer <your_token>"
echo "  5. Create a portfolio: POST /portfolios"
echo "  6. Add transactions: POST /transactions"
echo "  7. Sync market data: POST /portfolios/{id}/sync"
echo "  8. View valuation: GET /portfolios/{id}/valuation"
echo ""
echo "COMMON COMMANDS:"
echo "  Start frontend:   cd frontend && npm run dev"
echo "  Build frontend:   cd frontend && npm run build"
echo "  View logs:        $DOCKER_COMPOSE logs -f backend"
echo "  Run tests:        $DOCKER_COMPOSE exec backend pytest"
echo "  Stop services:    $DOCKER_COMPOSE down"
echo "  Fresh restart:    ./setup_project.sh --fresh"
echo ""
echo "API ENDPOINTS:"
echo "  Authentication:   /auth/login, /auth/register, /auth/me"
echo "  Portfolios:       /portfolios"
echo "  Transactions:     /transactions"
echo "  Sync Data:        /portfolios/{id}/sync"
echo "  Valuation:        /portfolios/{id}/valuation"
echo "  History:          /portfolios/{id}/valuation/history"
echo "  Analytics:        /portfolios/{id}/analytics"
echo ""
