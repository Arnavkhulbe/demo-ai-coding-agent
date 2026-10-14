"""Tests for shop.orders.

They fail for the same underlying reason as the pricing tests: order totals are
built on :func:`shop.pricing.apply_discount`.
"""

import pytest

from shop.orders import LineItem, Order


def make_widget_order() -> Order:
    """Two widgets at 50.00 each: subtotal 100.00."""
    return Order(items=[LineItem("Widget", 50.0, 2)])


def test_subtotal_is_unit_price_times_quantity():
    assert make_widget_order().subtotal == 100.0


def test_order_without_discount_only_adds_vat():
    assert make_widget_order().total() == 120.0


def test_order_applies_discount_then_vat():
    order = make_widget_order()
    order.discount_percent = 10
    # 100.00 - 10% = 90.00, then + 20% VAT = 108.00
    assert order.total() == 108.0


def test_discount_amount_is_reported():
    order = make_widget_order()
    order.discount_percent = 25
    assert order.discount_amount == 25.0


def test_summary_mentions_the_total():
    order = make_widget_order()
    assert "total $120.00" in order.summary()


def test_empty_order_totals_zero():
    assert Order().total() == 0.0
