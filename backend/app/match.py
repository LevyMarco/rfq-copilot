"""Stage 2: map each extracted line onto a real SKU.

Scoring is deliberately explainable. Every candidate carries the reasons it
scored what it scored, because the person reviewing the quote is a salesperson,
not an engineer, and "trust me, cosine similarity" is not an answer they can
act on.

Three signals, in order of how much they matter in this domain:

  1. a learned alias  -> the exact phrase was corrected by a human before
  2. attribute match  -> size and material are hard constraints, not hints
  3. token overlap    -> everything else
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List

from .aliases import lookup_alias
from .catalog import Product, load_catalog, normalize, parse_material, parse_size
from .models import ExtractedLine, MatchCandidate, MatchedLine

AUTO_ACCEPT = 0.82      # above this we fill the line in and let the human skim
AMBIGUOUS_GAP = 0.06    # top two this close together is a coin flip, so ask

_STOP = {"inch", "deg", "the", "for", "with", "and", "pcs", "ea", "qty", "of", "x"}


def _tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if t not in _STOP and len(t) > 1}


def _token_score(query: str, product: Product) -> float:
    q, p = _tokens(query), _tokens(product.haystack)
    if not q:
        return 0.0
    overlap = len(q & p) / len(q)
    fuzzy = SequenceMatcher(None, normalize(query), normalize(product.name)).ratio()
    return 0.7 * overlap + 0.3 * fuzzy


def score_product(line: ExtractedLine, product: Product) -> tuple[float, List[str]]:
    reasons: List[str] = []

    want_size = line.size or parse_size(line.raw_text)
    want_material = line.material or parse_material(line.raw_text)

    score = _token_score(f"{line.description} {line.raw_text}", product)
    reasons.append(f"text similarity {score:.2f}")

    if want_size:
        if normalize(want_size) == normalize(product.size):
            score += 0.30
            reasons.append(f"size {want_size} matches")
        else:
            score -= 0.35
            reasons.append(f"size mismatch: wanted {want_size}, SKU is {product.size}")

    if want_material:
        if normalize(want_material) == normalize(product.material):
            score += 0.22
            reasons.append(f"material {want_material} matches")
        else:
            score -= 0.25
            reasons.append(f"material mismatch: wanted {want_material}, SKU is {product.material}")

    # An explicit SKU in the text beats everything.
    if re.search(rf"\b{re.escape(product.sku)}\b", line.raw_text, re.I):
        score = 1.0
        reasons = [f"customer quoted our SKU {product.sku} directly"]

    return max(0.0, min(1.0, score)), reasons


def match_line(line: ExtractedLine, top_n: int = 3) -> MatchedLine:
    alias_sku = lookup_alias(line.description) or lookup_alias(line.raw_text)

    scored = []
    for product in load_catalog():
        score, reasons = score_product(line, product)
        if alias_sku and product.sku == alias_sku:
            score = max(score, 0.95)
            reasons.insert(0, "a human mapped this exact wording to this SKU before")
        scored.append(MatchCandidate(sku=product.sku, name=product.name,
                                     score=round(score, 3), reasons=reasons))

    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[:top_n]
    result = MatchedLine(extracted=line, candidates=top)

    if not top or top[0].score < 0.35:
        result.needs_review = True
        result.review_reason = "no plausible SKU in the catalog"
        result.confidence = top[0].score if top else 0.0
        return result

    best = top[0]
    result.chosen_sku = best.sku
    result.confidence = best.score

    if len(top) > 1 and (best.score - top[1].score) < AMBIGUOUS_GAP:
        result.needs_review = True
        result.review_reason = f"too close to call against {top[1].sku}"
    elif best.score < AUTO_ACCEPT:
        result.needs_review = True
        result.review_reason = "low confidence"
    else:
        result.needs_review = False

    return result


def match_all(lines: List[ExtractedLine]) -> List[MatchedLine]:
    return [match_line(line) for line in lines]
