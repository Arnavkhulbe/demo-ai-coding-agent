"""Order totals for the sample shop."""

from __future__ import annotations

from dataclasses import dataclass, field

from shop.pricing import add_vat, apply_discount, format_price


@dataclass
class LineItem:
    """One line on an order."""

    name: str
    unit_price: float
    quantity: int = 1

    @property
    def subtotal(self) -> float:
        return self.unit_price * self.quantity


@dataclass
class Order:
    """A collection of line items with an optional whole-order discount."""

    items: list[LineItem] = field(default_factory=list)
    discount_percent: float = 0.0

    @property
    def subtotal(self) -> float:
        return sum(item.subtotal for item in self.items)

    @property
    def discount_amount(self) -> float:
        return round(self.subtotal - apply_discount(self.subtotal, self.discount_percent), 2)

    def total(self) -> float:
        """Return the order total: discount first, then VAT."""
        discounted = apply_discount(self.subtotal, self.discount_percent)
        return add_vat(discounted)

    def summary(self) -> str:
        """A human-readable one-line receipt."""
        return (
            f"{len(self.items)} item(s), subtotal {format_price(self.subtotal)}, "
            f"discount {format_price(self.discount_amount)}, "
            f"total {format_price(self.total())}"
        )
