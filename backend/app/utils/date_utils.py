# backend/app/utils/date_utils.py
"""
Date utility functions for the Investment Analyzer.

This module provides shared date manipulation functions used across
multiple services. Centralizing these prevents code duplication and
ensures consistent behavior.

Usage:
    from app.utils.date_utils import get_business_days

    days = get_business_days(start_date, end_date)
"""

from datetime import date, timedelta


def get_business_days(start_date: date, end_date: date) -> list[date]:
    """
    Get list of business days (weekdays) in a date range.

    Business days are Monday through Friday (weekday() < 5).
    This is a simplified check that doesn't account for market holidays.

    Args:
        start_date: First date in range (inclusive)
        end_date: Last date in range (inclusive)

    Returns:
        List of dates that are weekdays, sorted chronologically

    Example:
        >>> get_business_days(date(2024, 1, 1), date(2024, 1, 7))
        [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3),
         date(2024, 1, 4), date(2024, 1, 5)]  # Mon-Fri
    """
    days = []
    current = start_date

    while current <= end_date:
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            days.append(current)
        current += timedelta(days=1)

    return days


def is_business_day(d: date) -> bool:
    """
    Check if a date is a business day (weekday).

    Args:
        d: Date to check

    Returns:
        True if Monday-Friday, False if Saturday-Sunday
    """
    return d.weekday() < 5


def next_business_day(d: date) -> date:
    """
    Get the next business day after a given date.

    If the given date is a Friday, returns the following Monday.
    If the given date is a weekday, returns the next day.

    Args:
        d: Starting date

    Returns:
        The next business day
    """
    next_day = d + timedelta(days=1)
    while next_day.weekday() >= 5:  # Skip weekend
        next_day += timedelta(days=1)
    return next_day


def previous_business_day(d: date) -> date:
    """
    Get the previous business day before a given date.

    If the given date is a Monday, returns the previous Friday.
    If the given date is a weekday, returns the previous day.

    Args:
        d: Starting date

    Returns:
        The previous business day
    """
    prev_day = d - timedelta(days=1)
    while prev_day.weekday() >= 5:  # Skip weekend
        prev_day -= timedelta(days=1)
    return prev_day
