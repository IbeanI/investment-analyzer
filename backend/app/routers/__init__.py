# backend/app/routers/__init__.py
"""
API routers for the Investment Portfolio Analyzer.

Each router handles a specific domain:
- assets: Global asset registry (AAPL, MSFT, etc.)
- portfolios: User portfolio management
- transactions: Buy/sell transaction records
- users: User account management
"""

from app.routers.assets import router as assets_router
from app.routers.portfolios import router as portfolios_router
from app.routers.transactions import router as transactions_router

# Will be added as we create them:
# from app.routers.users import router as users_router

__all__ = [
    "assets_router",
    "portfolios_router",
    "transactions_router",
    # "users_router",
]
