"""Shared data shapes for the RFQ pipeline.

The whole system is three stages: extract -> match -> price.
Each stage has an input and an output type here so the boundaries stay honest
and the eval harness can assert on them without importing FastAPI.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------- extraction

class ExtractedLine(BaseModel):
    """One line item as the customer wrote it, before we know what it maps to."""

    raw_text: str = Field(description="The fragment of the RFQ this line came from")
    description: str = Field(description="Cleaned-up product description")
    quantity: float = 1
    unit: Optional[str] = None
    size: Optional[str] = None
    material: Optional[str] = None
    notes: Optional[str] = None


class ExtractionResult(BaseModel):
    lines: List[ExtractedLine] = []
    customer_name: Optional[str] = None
    requested_delivery: Optional[str] = None
    extractor: Literal["llm", "heuristic"] = "heuristic"
    warnings: List[str] = []


# ------------------------------------------------------------------ matching

class MatchCandidate(BaseModel):
    sku: str
    name: str
    score: float = Field(description="0-1, higher is better")
    reasons: List[str] = []


class MatchedLine(BaseModel):
    extracted: ExtractedLine
    candidates: List[MatchCandidate] = []
    chosen_sku: Optional[str] = None
    confidence: float = 0.0
    needs_review: bool = True
    review_reason: Optional[str] = None


# ------------------------------------------------------------------- pricing

class QuoteLine(BaseModel):
    line_no: int
    raw_text: str
    description: str
    quantity: float
    sku: Optional[str] = None
    product_name: Optional[str] = None
    unit: Optional[str] = None
    unit_list_price: Optional[float] = None
    discount_pct: float = 0.0
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    stock_qty: Optional[int] = None
    availability: Literal["in_stock", "partial", "backorder", "unknown"] = "unknown"
    lead_time_days: Optional[int] = None
    confidence: float = 0.0
    needs_review: bool = True
    review_reason: Optional[str] = None
    candidates: List[MatchCandidate] = []


class Quote(BaseModel):
    quote_id: str
    customer_name: Optional[str] = None
    customer_tier: str = "standard"
    lines: List[QuoteLine] = []
    subtotal: float = 0.0
    lines_needing_review: int = 0
    extractor: str = "heuristic"
    warnings: List[str] = []


# ------------------------------------------------------------- learning loop

class LineCorrection(BaseModel):
    """What a human changed on a line. This is the training signal."""

    raw_text: str
    description: str
    wrong_sku: Optional[str] = None
    correct_sku: str


class CorrectionBatch(BaseModel):
    quote_id: str
    corrections: List[LineCorrection] = []


# ---------------------------------------------------------------- API inputs

class QuoteRequest(BaseModel):
    text: str = Field(description="Raw RFQ text: pasted email, notes, whatever")
    customer_tier: Literal["standard", "silver", "gold"] = "standard"
    use_llm: bool = True
