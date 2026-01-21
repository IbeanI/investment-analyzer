# Investment Portfolio Analyzer

A comprehensive investment portfolio tracking and analytics platform built with FastAPI, PostgreSQL, and Python.

## Features

- **Portfolio Management**: Create and manage multiple investment portfolios
- **Transaction Tracking**: Record buy/sell transactions with full cost basis tracking
- **Bulk Upload**: Import transactions from CSV files with flexible date format support
- **Market Data Sync**: Automatic price fetching from Yahoo Finance with circuit breaker protection
- **Multi-Currency Support**: Handle portfolios with assets in different currencies with automatic FX conversion
- **Real-Time Valuation**: Portfolio valuation with holdings breakdown and P&L calculations
- **Performance Analytics**: TWR, IRR/XIRR, CAGR, and simple returns
- **Risk Metrics**: Volatility, Sharpe ratio, Sortino ratio, Max Drawdown, VaR/CVaR
- **Benchmark Comparison**: Beta, Alpha, Correlation, Tracking Error vs market indices
- **Proxy Backcasting**: Fill historical price gaps using proxy assets (beta feature)
- **Rate Limiting**: API protection with configurable limits per endpoint type

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

### 2. Add Transactions

```bash
curl -X POST "http://localhost:8000/portfolios/1/transactions" \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "AAPL",
    "exchange": "NASDAQ",
    "transaction_type": "BUY",
    "date": "2024-01-15T10:00:00Z",
    "quantity": "10",
    "price_per_share": "185.00",
    "currency": "USD",
    "exchange_rate": "0.92"
  }'
```

### 3. Upload Transactions from CSV

```bash
curl -X POST "http://localhost:8000/portfolios/1/upload" \
  -F "file=@transactions.csv" \
  -F "date_format=US"
```

### 4. Sync Market Data

```bash
curl -X POST "http://localhost:8000/portfolios/1/sync"
```

### 5. View Valuation

```bash
curl "http://localhost:8000/portfolios/1/valuation"
```

### 6. Get Analytics

```bash
# Full analytics (performance + risk + benchmark)
curl "http://localhost:8000/portfolios/1/analytics?start_date=2024-01-01&end_date=2024-12-31&benchmark=SPY"

# Performance only
curl "http://localhost:8000/portfolios/1/analytics/performance?start_date=2024-01-01&end_date=2024-12-31"

# Risk metrics only
curl "http://localhost:8000/portfolios/1/analytics/risk?start_date=2024-01-01&end_date=2024-12-31"
```

## API Endpoints

### Portfolios
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios` | GET | List all portfolios |
| `/portfolios` | POST | Create a portfolio |
| `/portfolios/{id}` | GET | Get portfolio details |
| `/portfolios/{id}` | PATCH | Update portfolio |
| `/portfolios/{id}` | DELETE | Delete portfolio |
| `/portfolios/{id}/settings` | GET | Get portfolio settings |
| `/portfolios/{id}/settings` | PATCH | Update portfolio settings |

### Transactions
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios/{id}/transactions` | GET | List transactions (paginated) |
| `/portfolios/{id}/transactions` | POST | Add a transaction |
| `/portfolios/{id}/transactions/{txn_id}` | GET | Get transaction details |
| `/portfolios/{id}/transactions/{txn_id}` | PATCH | Update transaction |
| `/portfolios/{id}/transactions/{txn_id}` | DELETE | Delete transaction |

### Upload
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios/{id}/upload` | POST | Upload transactions from file |
| `/upload/formats` | GET | List supported file formats |

### Market Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios/{id}/sync` | POST | Sync market data for portfolio |
| `/portfolios/{id}/sync/status` | GET | Get sync status |

### Valuation
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios/{id}/valuation` | GET | Current portfolio valuation |
| `/portfolios/{id}/valuation/history` | GET | Historical valuation time series |

### Analytics
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolios/{id}/analytics` | GET | Full analytics (performance + risk + benchmark) |
| `/portfolios/{id}/analytics/performance` | GET | Performance metrics (TWR, IRR, CAGR) |
| `/portfolios/{id}/analytics/risk` | GET | Risk metrics (Volatility, Sharpe, Drawdown) |
| `/portfolios/{id}/analytics/benchmark` | GET | Benchmark comparison (Beta, Alpha) |

### Assets
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/assets` | GET | List all assets |
| `/assets` | POST | Create an asset |
| `/assets/{id}` | GET | Get asset details |
| `/assets/{id}` | PATCH | Update asset |

### Health
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/ready` | GET | Readiness check (includes DB) |

## Analytics Metrics

### Performance Metrics
- **Simple Return**: Basic (End - Start) / Start calculation
- **TWR (Time-Weighted Return)**: Removes cash flow bias using Daily Linking Method
- **IRR/XIRR**: Money-weighted return with exact dates (Newton-Raphson solver)
- **CAGR**: Compound Annual Growth Rate

### Risk Metrics
- **Volatility**: Annualized standard deviation of returns
- **Sharpe Ratio**: Risk-adjusted return (excess return / volatility)
- **Sortino Ratio**: Downside risk-adjusted return
- **Max Drawdown**: Largest peak-to-trough decline with recovery tracking
- **VaR/CVaR**: Value at Risk at 95% confidence level
- **Win Rate**: Percentage of positive return days

### Benchmark Metrics
- **Beta**: Systematic risk relative to benchmark
- **Alpha**: Jensen's Alpha (excess return above expected)
- **Correlation**: How closely portfolio tracks benchmark
- **Tracking Error**: Standard deviation of return differences
- **Information Ratio**: Active return per unit of tracking risk

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
├── setup_project.sh          # Main setup script
├── docker-compose.yml        # Docker services configuration
├── .env.example              # Environment template
└── backend/
    ├── pyproject.toml        # Python dependencies (Poetry)
    ├── alembic/              # Database migrations
    ├── tests/                # Test suite
    │   ├── conftest.py       # Test fixtures
    │   ├── routers/          # API endpoint tests
    │   ├── schemas/          # Schema validation tests
    │   └── services/         # Service layer tests
    └── app/
        ├── main.py           # FastAPI application entry point
        ├── config.py         # Pydantic settings configuration
        ├── database.py       # SQLAlchemy session management
        ├── models.py         # ORM models (Portfolio, Asset, Transaction, etc.)
        ├── dependencies.py   # Dependency injection
        ├── middleware/       # ASGI middleware
        │   ├── correlation.py    # Request correlation ID tracking
        │   └── rate_limit.py     # Rate limiting with slowapi
        ├── routers/          # API endpoints
        │   ├── analytics.py      # Analytics endpoints
        │   ├── assets.py         # Asset management
        │   ├── portfolios.py     # Portfolio CRUD
        │   ├── portfolio_settings.py  # Portfolio preferences
        │   ├── sync.py           # Market data sync
        │   ├── transactions.py   # Transaction management
        │   ├── upload.py         # File upload
        │   └── valuation.py      # Valuation endpoints
        ├── schemas/          # Pydantic request/response schemas
        │   ├── analytics.py      # Analytics response schemas
        │   ├── assets.py         # Asset schemas
        │   ├── portfolios.py     # Portfolio schemas
        │   ├── transactions.py   # Transaction schemas
        │   ├── valuation.py      # Valuation schemas
        │   └── validators.py     # Reusable validation functions
        ├── services/         # Business logic layer
        │   ├── exceptions.py         # Domain exceptions
        │   ├── constants.py          # Business constants
        │   ├── circuit_breaker.py    # Circuit breaker for external APIs
        │   ├── asset_resolution.py   # Asset lookup/creation
        │   ├── fx_rate_service.py    # FX rate management
        │   ├── analytics/            # Analytics engine
        │   │   ├── service.py        # Analytics orchestrator
        │   │   ├── returns.py        # Return calculations
        │   │   ├── risk.py           # Risk calculations
        │   │   └── benchmark.py      # Benchmark comparison
        │   ├── market_data/          # Market data services
        │   │   ├── base.py           # Provider interface
        │   │   ├── yahoo.py          # Yahoo Finance provider
        │   │   └── sync_service.py   # Sync orchestration
        │   ├── upload/               # File upload processing
        │   │   ├── service.py        # Upload orchestration
        │   │   └── parsers/          # Format-specific parsers
        │   └── valuation/            # Valuation services
        │       ├── service.py        # Valuation orchestrator
        │       ├── calculators.py    # Point-in-time calculations
        │       └── history_calculator.py  # Time series
        └── utils/            # Utilities
            ├── logging.py        # Logging configuration
            ├── context.py        # Request context (correlation ID)
            └── date_utils.py     # Date helpers
```

## Architecture

### Tech Stack
- **FastAPI**: Modern Python web framework with automatic OpenAPI docs
- **SQLAlchemy 2.0**: ORM with async support
- **PostgreSQL**: Primary database with connection pooling
- **Alembic**: Database migrations
- **Pydantic v2**: Data validation with Decimal support for financial precision
- **Yahoo Finance**: Market data provider (via yfinance)
- **slowapi**: Rate limiting

### Design Principles
- **Layered Architecture**: Routers → Services → Models with clear separation
- **Dependency Injection**: Services injected via FastAPI's Depends
- **Domain Exceptions**: Services raise domain-specific exceptions, routers convert to HTTP
- **Decimal Precision**: All financial calculations use Decimal (never float for money)
- **GIPS Compliance**: Investment period detection for accurate return calculations

### Key Features
- **Circuit Breaker**: Protects external API calls with automatic recovery
- **Rate Limiting**: Configurable limits per endpoint type (read, write, sync, upload)
- **Correlation ID**: Request tracing across log entries
- **LRU Caching**: Thread-safe analytics cache with TTL

## License

MIT
