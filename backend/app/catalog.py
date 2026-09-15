"""Catalog loading plus the text normalisation both the catalog and the
incoming RFQ text have to go through before anything can be compared.

Real distributors do not have clean catalogs. The normalisation here is
deliberately opinionated about the things that actually break matching in
this domain: fractional inch sizes written five different ways, material
codes with and without spaces, and metric thread callouts.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog.csv"


@dataclass
class Product:
    sku: str
    name: str
    category: str
    size: str
    material: str
    pressure_rating: str
    unit: str
    list_price: float
    stock_qty: int
    lead_time_days: int

    @property
    def haystack(self) -> str:
        return normalize(f"{self.name} {self.category} {self.material} {self.size}")


# --------------------------------------------------------------- normalising

# "1/2 inch", "1/2in", "0.5\"", "DN15" all mean the same thing to a buyer.
_SIZE_ALIASES = {
    "0.25": '1/4"', "1/4": '1/4"', "dn8": '1/4"',
    "0.375": '3/8"', "3/8": '3/8"', "dn10": '3/8"',
    "0.5": '1/2"', "1/2": '1/2"', "dn15": '1/2"',
    "0.75": '3/4"', "3/4": '3/4"', "dn20": '3/4"',
    "1": '1"', "dn25": '1"',
    "1.5": '1-1/2"', "1 1/2": '1-1/2"', "1-1/2": '1-1/2"', "dn40": '1-1/2"',
    "2": '2"', "dn50": '2"',
    "3": '3"', "dn80": '3"',
    "4": '4"', "dn100": '4"',
}

_MATERIAL_ALIASES = {
    "ss316": "SS316", "316": "SS316", "316ss": "SS316", "aisi 316": "SS316",
    "stainless 316": "SS316", "inox 316": "SS316",
    "ss304": "SS304", "304": "SS304", "304ss": "SS304", "aisi 304": "SS304",
    "stainless": "SS304", "stainless steel": "SS304", "inox": "SS304",
    "cs": "CS", "carbon steel": "CS", "carbon": "CS", "a105": "CS",
    "brass": "Brass", "bronze": "Brass",
    "pvc": "PVC",
    "zinc": "Zinc Plated", "zinc plated": "Zinc Plated", "galvanized": "Zinc Plated",
}

_NOISE = re.compile(r"[^a-z0-9/\-\. ]+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = (text or "").lower().replace('"', " inch ").replace("''", " inch ")
    text = text.replace("deg.", "deg").replace("°", " deg ")
    text = _NOISE.sub(" ", text)
    return _WS.sub(" ", text).strip()


def parse_size(text: str) -> Optional[str]:
    """Pull a nominal size out of free text and return the canonical form."""
    t = (text or "").lower()

    m = re.search(r"\bdn\s?(\d{1,3})\b", t)
    if m:
        return _SIZE_ALIASES.get(f"dn{m.group(1)}")

    # Metric thread, e.g. M12 or M12x50. A trailing \\b would fail on "M12x50"
    # because x is a word character, so guard on "not another digit" instead.
    m = re.search(r"\bm(\d{1,2})(?![0-9])", t)
    if m:
        return f"M{m.group(1)}"

    m = re.search(r"\b(\d)\s*[- ]\s*(\d/\d)\s*(?:\"|inch|in\b)", t)   # 1-1/2"
    if m:
        return _SIZE_ALIASES.get(f"{m.group(1)}-{m.group(2)}")

    m = re.search(r"\b(\d/\d)\s*(?:\"|inch|in\b)?", t)                # 1/2"
    if m:
        return _SIZE_ALIASES.get(m.group(1))

    m = re.search(r"\b(\d(?:\.\d+)?)\s*(?:\"|inch|in\b)", t)          # 2"
    if m:
        return _SIZE_ALIASES.get(m.group(1).rstrip("0").rstrip("."))

    m = re.search(r"\b(6[23]\d\d)\b", t)                              # bearing code
    if m:
        return m.group(1)

    return None


def parse_material(text: str) -> Optional[str]:
    t = normalize(text)
    # Longest alias first so "stainless 316" beats "stainless".
    for alias in sorted(_MATERIAL_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return _MATERIAL_ALIASES[alias]
    return None


def parse_quantity(text: str) -> Optional[float]:
    t = (text or "").lower()
    patterns = [
        r"\bqty[:\s]*(\d+(?:[.,]\d+)?)",
        r"\b(\d+(?:[.,]\d+)?)\s*(?:pcs?|pieces?|ea\b|units?|un\b|nos?\b)",
        r"\b(\d+(?:[.,]\d+)?)\s*(?:m|meters?|mtr)\b",
        r"^\s*(\d+(?:[.,]\d+)?)\s*[xX]\s",
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


# ------------------------------------------------------------------- loading

@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> List[Product]:
    p = Path(path) if path else CATALOG_PATH
    products: List[Product] = []
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            products.append(
                Product(
                    sku=row["sku"],
                    name=row["name"],
                    category=row["category"],
                    size=row["size"],
                    material=row["material"],
                    pressure_rating=row["pressure_rating"],
                    unit=row["unit"],
                    list_price=float(row["list_price"]),
                    stock_qty=int(row["stock_qty"]),
                    lead_time_days=int(row["lead_time_days"]),
                )
            )
    return products


def by_sku(sku: str) -> Optional[Product]:
    for p in load_catalog():
        if p.sku == sku:
            return p
    return None
