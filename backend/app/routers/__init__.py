# backend/app/routers/__init__.py
"""
API routers for the Investment Portfolio Analyzer.

Each router handles a specific domain:
- assets: Global asset registry (AAPL, MSFT, etc.)
- portfolios: User portfolio management
- transactions: Buy/sell transaction records
- upload: File upload for bulk transaction import
- sync: Market data synchronization (Phase 3)
- valuation: Portfolio valuation and performance (Phase 4)
- analytics: Portfolio analytics (performance, risk, benchmark) (Phase 5)
"""

from app.routers.analytics import router as analytics_router
from app.routers.assets import router as assets_router
from app.routers.portfolio_settings import router as portfolio_settings_router
from app.routers.portfolios import router as portfolios_router
from app.routers.sync import router as sync_router
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
    "sync_router",
    "valuation_router",
    "analytics_router",
    # "users_router",
    "portfolio_settings_router",
]
