"""Tests for shop.pricing.

These tests describe the *expected* behaviour. Several of them fail against the
current implementation — that failure is the bug the agent has to fix.
"""

import pytest

from shop.pricing import add_vat, apply_discount, format_price


def test_apply_discount_reduces_the_price_by_the_given_percentage():
    assert apply_discount(100.0, 20) == 80.0


def test_apply_discount_with_zero_percent_changes_nothing():
    assert apply_discount(50.0, 0) == 50.0


def test_apply_discount_of_one_hundred_percent_is_free():
    assert apply_discount(50.0, 100) == 0.0


def test_apply_discount_rounds_nothing_away():
    assert apply_discount(9.99, 10) == pytest.approx(8.991)


def test_apply_discount_rejects_a_negative_price():
    with pytest.raises(ValueError):
        apply_discount(-1.0, 10)


def test_apply_discount_rejects_an_out_of_range_percentage():
    with pytest.raises(ValueError):
        apply_discount(10.0, 150)


def test_add_vat_includes_the_vat_rate():
    assert add_vat(100.0) == 120.0


def test_format_price_uses_two_decimals():
    assert format_price(1234.5) == "$1,234.50"
