"""Stage 3: price the matched lines and say whether we can actually ship them.

Pricing rules are plain Python, not an LLM call. Anything a customer could
dispute on an invoice should be deterministic and diffable. The model's job is
to read the email, not to decide what a customer pays.
"""

from __future__ import annotations

import uuid
from typing import List

from .catalog import by_sku
from .models import MatchedLine, Quote, QuoteLine

TIER_DISCOUNT = {"standard": 0.00, "silver": 0.05, "gold": 0.10}

# (minimum qty, extra discount)
VOLUME_BREAKS = [(500, 0.12), (100, 0.08), (25, 0.04), (10, 0.02)]

MAX_DISCOUNT = 0.25


def volume_discount(qty: float) -> float:
    for threshold, disc in VOLUME_BREAKS:
        if qty >= threshold:
            return disc
    return 0.0


def build_quote(matched: List[MatchedLine], customer_tier: str = "standard",
                customer_name: str | None = None, extractor: str = "heuristic",
                warnings: List[str] | None = None) -> Quote:
    quote = Quote(
        quote_id=uuid.uuid4().hex[:10],
        customer_name=customer_name,
        customer_tier=customer_tier,
        extractor=extractor,
        warnings=list(warnings or []),
    )

    for i, m in enumerate(matched, start=1):
        line = QuoteLine(
            line_no=i,
            raw_text=m.extracted.raw_text,
            description=m.extracted.description,
            quantity=m.extracted.quantity,
            confidence=round(m.confidence, 3),
            needs_review=m.needs_review,
            review_reason=m.review_reason,
            candidates=m.candidates,
        )

        product = by_sku(m.chosen_sku) if m.chosen_sku else None
        if product:
            disc = min(TIER_DISCOUNT.get(customer_tier, 0.0)
                       + volume_discount(m.extracted.quantity), MAX_DISCOUNT)
            unit_price = round(product.list_price * (1 - disc), 2)

            line.sku = product.sku
            line.product_name = product.name
            line.unit = product.unit
            line.unit_list_price = product.list_price
            line.discount_pct = round(disc * 100, 1)
            line.unit_price = unit_price
            line.line_total = round(unit_price * m.extracted.quantity, 2)
            line.stock_qty = product.stock_qty
            line.lead_time_days = product.lead_time_days

            if product.stock_qty >= m.extracted.quantity:
                line.availability = "in_stock"
            elif product.stock_qty > 0:
                line.availability = "partial"
                line.needs_review = True
                line.review_reason = (
                    f"only {product.stock_qty} of {m.extracted.quantity:g} on hand, "
                    f"balance in {product.lead_time_days} days"
                )
            else:
                line.availability = "backorder"
                line.needs_review = True
                line.review_reason = f"out of stock, lead time {product.lead_time_days} days"

        quote.lines.append(line)

    quote.subtotal = round(sum(l.line_total or 0 for l in quote.lines), 2)
    quote.lines_needing_review = sum(1 for l in quote.lines if l.needs_review)
    return quote
