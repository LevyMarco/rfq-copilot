"""HTTP surface.

Deliberately small. Four endpoints is everything the UI needs, and everything
a customer's own system would need if they wanted to call this instead of
using the UI.
"""

from __future__ import annotations

import csv
import io
from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .aliases import confusion_pairs, list_aliases, record_alias
from .catalog import load_catalog
from .extract import extract
from .match import match_all
from .models import CorrectionBatch, Quote, QuoteRequest
from .pricing import build_quote

app = FastAPI(
    title="RFQ Copilot",
    version="0.1.0",
    description="Turns a messy request-for-quote email into a reviewable draft quote.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_QUOTES: dict[str, Quote] = {}   # swap for a real store when it matters


@app.get("/health")
def health():
    return {"status": "ok", "catalog_size": len(load_catalog())}


@app.get("/catalog")
def catalog(q: str | None = None, limit: int = 50):
    items = load_catalog()
    if q:
        needle = q.lower()
        items = [p for p in items if needle in p.name.lower() or needle in p.sku.lower()]
    return [p.__dict__ for p in items[:limit]]


@app.post("/quote", response_model=Quote)
def create_quote(req: QuoteRequest):
    if not req.text.strip():
        raise HTTPException(400, "empty RFQ text")

    extraction = extract(req.text, use_llm=req.use_llm)
    matched = match_all(extraction.lines)
    quote = build_quote(
        matched,
        customer_tier=req.customer_tier,
        customer_name=extraction.customer_name,
        extractor=extraction.extractor,
        warnings=extraction.warnings,
    )
    _QUOTES[quote.quote_id] = quote
    return quote


@app.post("/quote/upload", response_model=Quote)
async def create_quote_from_file(file: UploadFile = File(...),
                                 customer_tier: str = "standard"):
    """Accept a CSV or plain-text RFQ. Buyers send both."""
    raw = (await file.read()).decode("utf-8", errors="replace")
    if file.filename and file.filename.lower().endswith(".csv"):
        rows = list(csv.reader(io.StringIO(raw)))
        raw = "\n".join(" ".join(cell for cell in row if cell) for row in rows)
    return create_quote(QuoteRequest(text=raw, customer_tier=customer_tier))  # type: ignore[arg-type]


@app.post("/quote/{quote_id}/corrections")
def submit_corrections(quote_id: str, batch: CorrectionBatch):
    """A salesperson fixed some lines. Store the mapping so next time we get it
    right on the first pass."""
    quote = _QUOTES.get(quote_id)
    if not quote:
        raise HTTPException(404, "unknown quote")

    learned = 0
    for c in batch.corrections:
        record_alias(c.description or c.raw_text, c.correct_sku, wrong_sku=c.wrong_sku)
        learned += 1
    return {"learned": learned, "aliases_total": len(list_aliases(limit=10_000))}


@app.get("/aliases")
def aliases():
    return {"aliases": list_aliases(), "confusion": confusion_pairs()}


@app.post("/quote/{quote_id}/export")
def export_quote(quote_id: str):
    quote = _QUOTES.get(quote_id)
    if not quote:
        raise HTTPException(404, "unknown quote")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["line", "sku", "product", "qty", "unit", "unit_price",
                "line_total", "availability", "lead_time_days", "confidence"])
    for l in quote.lines:
        w.writerow([l.line_no, l.sku or "", l.product_name or l.description,
                    l.quantity, l.unit or "", l.unit_price or "",
                    l.line_total or "", l.availability, l.lead_time_days or "",
                    l.confidence])
    w.writerow([])
    w.writerow(["", "", "", "", "", "SUBTOTAL", quote.subtotal])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="quote-{quote_id}.csv"'},
    )
