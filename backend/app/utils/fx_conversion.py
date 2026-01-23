# backend/app/utils/fx_conversion.py
"""
FX Rate Conversion Utilities

This module clarifies the two different exchange rate conventions used in the system:

1. BROKER RATE (Transaction.exchange_rate):
   Convention: "1 portfolio_currency = X transaction_currency"
   Example: If portfolio is EUR and transaction is USD, rate=1.10 means 1 EUR = 1.10 USD
   Usage: To convert USD → EUR, DIVIDE by rate

2. FX SERVICE RATE (FXRateService.get_rate):
   Convention: "1 base_currency = X quote_currency" (standard FX notation)
   Example: get_rate(USD, EUR) returns rate where 1 USD = X EUR
   Usage: To convert USD → EUR, MULTIPLY by rate

These utilities provide explicit, named functions to prevent confusion.
"""

from decimal import Decimal


def convert_using_broker_rate(
    amount_transaction: Decimal,
    broker_rate: Decimal,
) -> Decimal:
    """
    Convert transaction currency to portfolio currency using broker rate.

    Broker rate convention: 1 portfolio_currency = broker_rate × transaction_currency
    Therefore: portfolio_amount = transaction_amount / broker_rate

    Example:
        - Portfolio currency: EUR
        - Transaction currency: USD
        - Broker rate: 1.10 (meaning 1 EUR = 1.10 USD)
        - Transaction amount: 110 USD
        - Portfolio amount: 110 / 1.10 = 100 EUR

    Args:
        amount_transaction: Amount in transaction currency
        broker_rate: Broker's FX rate (1 portfolio = X transaction)

    Returns:
        Amount converted to portfolio currency
    """
    if broker_rate == 0:
        raise ValueError("Broker rate cannot be zero")
    return amount_transaction / broker_rate


def convert_using_fx_rate(
    amount_base: Decimal,
    fx_rate: Decimal,
) -> Decimal:
    """
    Convert base currency to quote currency using FX service rate.

    FX rate convention: 1 base_currency = fx_rate × quote_currency
    Therefore: quote_amount = base_amount × fx_rate

    Example:
        - Base currency: USD
        - Quote currency: EUR
        - FX rate: 0.91 (meaning 1 USD = 0.91 EUR)
        - Base amount: 110 USD
        - Quote amount: 110 × 0.91 = 100.10 EUR

    Args:
        amount_base: Amount in base currency
        fx_rate: FX rate (1 base = X quote)

    Returns:
        Amount converted to quote currency
    """
    return amount_base * fx_rate


def broker_rate_to_fx_rate(broker_rate: Decimal) -> Decimal:
    """
    Convert broker rate convention to FX rate convention.

    Broker: 1 portfolio = X transaction → to convert, DIVIDE
    FX:     1 transaction = X portfolio → to convert, MULTIPLY

    The FX rate is the inverse of the broker rate.

    Example:
        - Broker rate: 1.10 (1 EUR = 1.10 USD)
        - FX rate: 0.909 (1 USD = 0.909 EUR)

    Args:
        broker_rate: Rate in broker convention

    Returns:
        Equivalent rate in FX convention
    """
    if broker_rate == 0:
        raise ValueError("Broker rate cannot be zero")
    return Decimal("1") / broker_rate


def fx_rate_to_broker_rate(fx_rate: Decimal) -> Decimal:
    """
    Convert FX rate convention to broker rate convention.

    The inverse of broker_rate_to_fx_rate.

    Args:
        fx_rate: Rate in FX convention

    Returns:
        Equivalent rate in broker convention
    """
    if fx_rate == 0:
        raise ValueError("FX rate cannot be zero")
    return Decimal("1") / fx_rate
