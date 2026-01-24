# backend/app/routers/portfolio_settings.py
"""
Portfolio Settings endpoints.

Provides endpoints for managing portfolio-level settings and preferences.

Key features:
- Get current settings (auto-creates defaults if not exist)
- Update settings (partial update, only send what you want to change)
- Clear warnings when enabling/disabling features

Design:
- Settings are automatically created with defaults on first access
- Default: enable_proxy_backcasting = True (opt-out model)
- Warnings returned when disabling important features

Endpoints:
    GET  /portfolios/{id}/settings  - Get settings (creates defaults if needed)
    PATCH /portfolios/{id}/settings - Update settings
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, User
from app.schemas.portfolio_settings import (
    PortfolioSettingsResponse,
    PortfolioSettingsUpdate,
    PortfolioSettingsUpdateResponse,
    BackcastingMethod,
)
from app.services.portfolio_settings_service import PortfolioSettingsService
from app.dependencies import get_current_user, get_portfolio_with_owner_check

logger = logging.getLogger(__name__)

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/portfolios",
    tags=["Portfolio Settings"],
)


# =============================================================================
# DEPENDENCIES
# =============================================================================

def get_settings_service() -> PortfolioSettingsService:
    """Dependency that provides the portfolio settings service."""
    return PortfolioSettingsService()


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/{portfolio_id}/settings",
    response_model=PortfolioSettingsResponse,
    summary="Get portfolio settings",
    response_description="Current portfolio settings",
    responses={
        200: {
            "description": "Settings retrieved successfully",
            "model": PortfolioSettingsResponse,
        },
        401: {
            "description": "Not authenticated",
        },
        403: {
            "description": "Not authorized to access this portfolio",
        },
        404: {
            "description": "Portfolio not found",
        },
    },
)
def get_portfolio_settings(
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        db: Session = Depends(get_db),
        service: PortfolioSettingsService = Depends(get_settings_service),
) -> PortfolioSettingsResponse:
    """
    Get settings for a portfolio.

    If settings don't exist yet, they will be automatically created
    with default values:

    | Setting | Default | Description |
    |---------|---------|-------------|
    | `enable_proxy_backcasting` | `true` | Generate synthetic prices for assets with data gaps |

    **Note:** Default settings use the "opt-out" model - features are enabled
    by default and users can disable them if desired.

    Raises **401** if not authenticated.
    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    logger.info(f"Getting settings for portfolio {portfolio_id}")

    # Domain exceptions (PortfolioNotFoundError) propagate to global handlers
    settings = service.get_or_create_default(db, portfolio_id)

    # Convert string to enum
    try:
        backcasting_method = BackcastingMethod(settings.backcasting_method)
    except ValueError:
        backcasting_method = BackcastingMethod.PROXY_PREFERRED

    return PortfolioSettingsResponse(
        id=settings.id,
        portfolio_id=settings.portfolio_id,
        enable_proxy_backcasting=settings.enable_proxy_backcasting,
        backcasting_method=backcasting_method,
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


@router.patch(
    "/{portfolio_id}/settings",
    response_model=PortfolioSettingsUpdateResponse,
    summary="Update portfolio settings",
    response_description="Updated portfolio settings",
    responses={
        200: {
            "description": "Settings updated successfully",
            "model": PortfolioSettingsUpdateResponse,
        },
        401: {
            "description": "Not authenticated",
        },
        403: {
            "description": "Not authorized to access this portfolio",
        },
        404: {
            "description": "Portfolio not found",
        },
    },
)
def update_portfolio_settings(
        settings_update: PortfolioSettingsUpdate,
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        db: Session = Depends(get_db),
        service: PortfolioSettingsService = Depends(get_settings_service),
) -> PortfolioSettingsUpdateResponse:
    """
    Update settings for a portfolio.

    Only send the fields you want to change. Omitted fields remain unchanged.

    **Available Settings:**

    | Setting | Type | Description |
    |---------|------|-------------|
    | `enable_proxy_backcasting` | boolean | (DEPRECATED) Use backcasting_method instead |
    | `backcasting_method` | string | Backcasting preference: proxy_preferred, cost_carry_only, or disabled |

    **Backcasting Methods:**

    - `proxy_preferred`: Use proxy backcasting when available, fall back to cost carry (default)
    - `cost_carry_only`: Always use cost carry, never use proxy data
    - `disabled`: No backcasting, leave historical gaps unfilled

    **Proxy Backcasting:**

    When enabled (proxy_preferred), the system will:
    1. Detect assets with missing historical price data
    2. Use similar proxy assets to generate synthetic prices
    3. Fill gaps in valuation history for more complete analytics

    When disabled:
    - No new synthetic prices will be generated
    - Existing synthetic prices are **not** removed
    - Historical valuations may show gaps or missing data

    **Warning:** Disabling backcasting may result in incomplete
    performance metrics for assets with limited price history.

    Raises **401** if not authenticated.
    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    logger.info(
        f"Updating settings for portfolio {portfolio_id}: "
        f"{settings_update.model_dump(exclude_unset=True)}"
    )

    # Domain exceptions (PortfolioNotFoundError) propagate to global handlers
    result = service.update_settings(
        db=db,
        portfolio_id=portfolio_id,
        enable_proxy_backcasting=settings_update.enable_proxy_backcasting,
        backcasting_method=settings_update.backcasting_method,
    )

    # Convert string to enum
    try:
        backcasting_method = BackcastingMethod(result.settings.backcasting_method)
    except ValueError:
        backcasting_method = BackcastingMethod.PROXY_PREFERRED

    return PortfolioSettingsUpdateResponse(
        id=result.settings.id,
        portfolio_id=result.settings.portfolio_id,
        enable_proxy_backcasting=result.settings.enable_proxy_backcasting,
        backcasting_method=backcasting_method,
        created_at=result.settings.created_at,
        updated_at=result.settings.updated_at,
        warning=result.warning,
    )
