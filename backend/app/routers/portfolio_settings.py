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
from app.models import Portfolio
from app.schemas.portfolio_settings import (
    PortfolioSettingsResponse,
    PortfolioSettingsUpdate,
    PortfolioSettingsUpdateResponse,
)
from app.services.portfolio_settings_service import PortfolioSettingsService

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


def get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    """
    Fetch a portfolio by ID or raise 404 if not found.

    Args:
        db: Database session
        portfolio_id: Portfolio ID to fetch

    Returns:
        Portfolio if found

    Raises:
        HTTPException: 404 if portfolio not found
    """
    portfolio = db.get(Portfolio, portfolio_id)

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio with id {portfolio_id} not found"
        )

    return portfolio


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
        404: {
            "description": "Portfolio not found",
        },
    },
)
def get_portfolio_settings(
        portfolio_id: int,
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
    """
    # Verify portfolio exists
    get_portfolio_or_404(db, portfolio_id)

    logger.info(f"Getting settings for portfolio {portfolio_id}")

    try:
        settings = service.get_or_create_default(db, portfolio_id)

        return PortfolioSettingsResponse(
            id=settings.id,
            portfolio_id=settings.portfolio_id,
            enable_proxy_backcasting=settings.enable_proxy_backcasting,
            created_at=settings.created_at,
            updated_at=settings.updated_at,
        )

    except ValueError as e:
        # Portfolio not found (shouldn't happen due to get_portfolio_or_404)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error getting settings for portfolio {portfolio_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get portfolio settings: {str(e)}",
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
        404: {
            "description": "Portfolio not found",
        },
    },
)
def update_portfolio_settings(
        portfolio_id: int,
        settings_update: PortfolioSettingsUpdate,
        db: Session = Depends(get_db),
        service: PortfolioSettingsService = Depends(get_settings_service),
) -> PortfolioSettingsUpdateResponse:
    """
    Update settings for a portfolio.

    Only send the fields you want to change. Omitted fields remain unchanged.

    **Available Settings:**

    | Setting | Type | Description |
    |---------|------|-------------|
    | `enable_proxy_backcasting` | boolean | Enable/disable synthetic price generation for assets with data gaps |

    **Proxy Backcasting (Beta Feature):**

    When enabled (default), the system will:
    1. Detect assets with missing historical price data
    2. Use similar proxy assets to generate synthetic prices
    3. Fill gaps in valuation history for more complete analytics

    When disabled:
    - No new synthetic prices will be generated
    - Existing synthetic prices are **not** removed
    - Historical valuations may show gaps or missing data

    **Warning:** Disabling proxy backcasting may result in incomplete
    performance metrics for assets with limited price history.
    """
    # Verify portfolio exists
    get_portfolio_or_404(db, portfolio_id)

    logger.info(
        f"Updating settings for portfolio {portfolio_id}: "
        f"{settings_update.model_dump(exclude_unset=True)}"
    )

    try:
        result = service.update_settings(
            db=db,
            portfolio_id=portfolio_id,
            enable_proxy_backcasting=settings_update.enable_proxy_backcasting,
        )

        return PortfolioSettingsUpdateResponse(
            id=result.settings.id,
            portfolio_id=result.settings.portfolio_id,
            enable_proxy_backcasting=result.settings.enable_proxy_backcasting,
            created_at=result.settings.created_at,
            updated_at=result.settings.updated_at,
            warning=result.warning,
        )

    except ValueError as e:
        # Portfolio not found (shouldn't happen due to get_portfolio_or_404)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating settings for portfolio {portfolio_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update portfolio settings: {str(e)}",
        )
