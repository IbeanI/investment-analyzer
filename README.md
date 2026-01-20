# Investment Portfolio Analyzer

A comprehensive investment portfolio tracking and analytics platform built with FastAPI, PostgreSQL, and Python.

## Features

- **Portfolio Management**: Create and manage multiple investment portfolios
- **Transaction Tracking**: Record buy/sell transactions with full cost basis tracking
- **Market Data Sync**: Automatic price fetching from Yahoo Finance
- **Multi-Currency Support**: Handle portfolios with assets in different currencies
- **Valuation**: Real-time portfolio valuation with FX conversion
- **Analytics**: Performance metrics, risk analysis, and benchmark comparison
- **Proxy Backcasting**: Fill historical price gaps using proxy assets

## Quick Start

### Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop) and Docker Compose
- Ports 8000 (API) and 5432 (PostgreSQL) available

### Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd investment-analyzer

# Run the setup script
chmod +x setup_project.sh
./setup_project.sh
```

The setup script will:
1. Create environment files if they don't exist
2. Build and start Docker containers
3. Initialize the database schema
4. Verify services are running

### Access the API

Once setup completes:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **PostgreSQL**: localhost:5432 (admin/password123)

## Usage

### 1. Create a Portfolio

```bash
curl -X POST "http://localhost:8000/portfolios" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Portfolio", "currency": "EUR"}'
```

Or use the Swagger UI at http://localhost:8000/docs

### 2. Add Transactions

```bash
curl -X POST "http://localhost:8000/portfolios/1/transactions" \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "AAPL",
    "exchange": "NASDAQ",
    "transaction_type": "BUY",
    "date": "2024-01-15",
    "quantity": 10,
    "price_per_share": 185.00,
    "currency": "USD",
    "exchange_rate": 0.92
  }'
```

### 3. Sync Market Data

```bash
curl -X POST "http://localhost:8000/portfolios/1/sync"
```

### 4. View Valuation

```bash
curl "http://localhost:8000/portfolios/1/valuation"
```

### 5. Get Analytics

```bash
curl "http://localhost:8000/portfolios/1/analytics?from_date=2024-01-01&to_date=2024-12-31"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios` | GET | List all portfolios |
| `/portfolios` | POST | Create a portfolio |
| `/portfolios/{id}` | GET | Get portfolio details |
| `/portfolios/{id}/transactions` | GET | List transactions |
| `/portfolios/{id}/transactions` | POST | Add a transaction |
| `/portfolios/{id}/sync` | POST | Sync market data |
| `/portfolios/{id}/valuation` | GET | Current valuation |
| `/portfolios/{id}/valuation/history` | GET | Historical valuation |
| `/portfolios/{id}/analytics` | GET | Full analytics |
| `/portfolios/{id}/analytics/performance` | GET | Performance metrics |
| `/portfolios/{id}/analytics/risk` | GET | Risk metrics |

## Development

### Run Tests

```bash
# Via Docker
docker-compose exec backend pytest

# Or locally (requires Poetry)
cd backend
poetry install
poetry run pytest
```

### View Logs

```bash
docker-compose logs -f backend
```

### Fresh Restart

To completely reset the database and start fresh:

```bash
./setup_project.sh --fresh
```

### Stop Services

```bash
docker-compose down
```

## Project Structure

```
investment-analyzer/
├── setup_project.sh        # Main setup script
├── docker-compose.yml      # Docker services configuration
├── .env.example            # Environment template
└── backend/
    ├── app/
    │   ├── main.py         # FastAPI application
    │   ├── models.py       # SQLAlchemy models
    │   ├── routers/        # API endpoints
    │   ├── schemas/        # Pydantic schemas
    │   └── services/       # Business logic
    ├── alembic/            # Database migrations
    ├── tests/              # Test suite
    └── scripts/            # Utility scripts
```

## Architecture

- **FastAPI**: Modern Python web framework with automatic OpenAPI docs
- **SQLAlchemy**: ORM for database operations
- **PostgreSQL**: Primary database
- **Alembic**: Database migrations
- **Yahoo Finance**: Market data provider (via yfinance)

## License

MIT
