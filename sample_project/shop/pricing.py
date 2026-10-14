"""Price calculations for the sample shop.

Percentages are always expressed as "percent", not as a fraction: 20 means 20%.
"""

from __future__ import annotations

#: Value added tax applied to every order, as a fraction (0.20 == 20%).
VAT_RATE = 0.20


def apply_discount(price: float, percent_off: float) -> float:
    """Return ``price`` after a percentage discount has been applied.

    ``percent_off`` is a percentage between 0 and 100. For example, a price of
    100.0 with ``percent_off=20`` should return 80.0.
    """
    if price < 0:
        raise ValueError("price must not be negative")
    if not 0 <= percent_off <= 100:
        raise ValueError("percent_off must be between 0 and 100")

    return price - price * percent_off


def add_vat(price: float) -> float:
    """Return ``price`` including VAT, rounded to two decimal places."""
    return round(price * (1 + VAT_RATE), 2)


def format_price(price: float) -> str:
    """Render a price the way it appears on a receipt."""
    return f"${price:,.2f}"
