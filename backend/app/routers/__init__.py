# backend/app/routers/__init__.py
"""
API routers for the Investment Portfolio Analyzer.

Each router handles a specific domain:
- assets: Global asset registry (AAPL, MSFT, etc.)
- portfolios: User portfolio management
- transactions: Buy/sell transaction records
- upload: File upload for bulk transaction import
- valuation: Portfolio valuation and performance (Phase 4)
"""

from app.routers.assets import router as assets_router
from app.routers.portfolios import router as portfolios_router
from app.routers.transactions import router as transactions_router
from app.routers.upload import router as upload_router
from app.routers.valuation import router as valuation_router

# Will be added as we create them:
# from app.routers.users import router as users_router

__all__ = [
    "assets_router",
    "portfolios_router",
    "transactions_router",
    "upload_router",
    "valuation_router",
    # "users_router",
]
