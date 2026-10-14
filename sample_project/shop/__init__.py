"""A small "shop" package used as the agent's demo target."""

from shop.orders import LineItem, Order
from shop.pricing import add_vat, apply_discount

__all__ = ["LineItem", "Order", "add_vat", "apply_discount"]
