"""Stage 1: turn a messy RFQ into structured line items.

Two extractors live here on purpose.

`llm_extract` is what you would actually ship. `heuristic_extract` is a
deterministic fallback that needs no API key and no network. It exists for
three reasons: the app has to run for someone who clones the repo without a
key, the eval suite has to be runnable in CI, and having a dumb baseline is
the only way to know whether the LLM is actually earning its cost.
"""

from __future__ import annotations

import json
import os
import re
from typing import List

from .catalog import parse_material, parse_quantity, parse_size
from .models import ExtractedLine, ExtractionResult

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You extract line items from industrial RFQ (request for quote) emails.

Return ONLY a JSON object, no prose, no markdown fences, with this shape:
{
  "customer_name": string or null,
  "requested_delivery": string or null,
  "lines": [
    {
      "raw_text": "the exact fragment of the email this line came from",
      "description": "cleaned up product description",
      "quantity": number,
      "unit": "EA" | "M" | null,
      "size": "nominal size as written, e.g. 1/2\\", 2\\", M12, 6205" or null,
      "material": "SS316 | SS304 | CS | Brass | PVC | Zinc Plated" or null,
      "notes": "anything the buyer said that affects the line" or null
    }
  ]
}

Rules:
- One object per distinct product the buyer wants. Do not merge two products.
- If a quantity is missing, use 1 and say so in notes.
- Never invent a part number. If the buyer gave no size or material, use null.
- Signature blocks, greetings and pleasantries are not line items.
- Keep raw_text verbatim from the email. It is used to trace the line back.
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def llm_extract(rfq_text: str) -> ExtractionResult:
    """Extract with Claude. Raises if no key is configured."""
    from anthropic import Anthropic  # imported lazily so the fallback path needs no dep

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": rfq_text}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    data = json.loads(_strip_fences(raw))

    result = ExtractionResult(extractor="llm")
    result.customer_name = data.get("customer_name")
    result.requested_delivery = data.get("requested_delivery")
    for item in data.get("lines", []):
        try:
            result.lines.append(ExtractedLine(**item))
        except Exception as exc:  # one bad line should not kill the quote
            result.warnings.append(f"dropped a malformed line: {exc}")
    return result


# ------------------------------------------------------------------ fallback

_SKIP = re.compile(
    r"^\s*(hi\b|hello|dear|good (morning|afternoon|evening)|thanks|thank you"
    r"|regards|best|kind regards|br\b|cheers|please quote|quote request|rfq\b"
    r"|let me know|sent from|--|__)",
    re.I,
)
# Signature blocks, footers and contact lines. Cheap to detect, expensive to miss.
_CONTACT = re.compile(r"[|@]|https?://|confidential|\+\d[\d\s().-]{6,}", re.I)
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[\.\)])\s*")


def heuristic_extract(rfq_text: str) -> ExtractionResult:
    """Split on lines, drop the pleasantries, regex out size/material/qty.

    Loses anything written as flowing prose. That gap is the point: the eval
    report shows exactly how much the LLM buys you over this baseline.
    """
    result = ExtractionResult(extractor="heuristic")

    for raw in rfq_text.splitlines():
        line = raw.strip()
        if len(line) < 6 or _SKIP.match(line):
            continue
        if _CONTACT.search(line):
            continue
        body = _BULLET.sub("", line)
        # A line with no letters is a total, a date or a page number.
        if not re.search(r"[a-zA-Z]{3}", body):
            continue
        # Known limitation of the baseline: every real line item in this catalog
        # carries a size, a quantity or a bearing code, so a line with no digit
        # at all is almost always a name, a greeting or a footer. The LLM
        # extractor has no such constraint, which is most of its lift.
        if not re.search(r"\d", body):
            continue

        qty = parse_quantity(body)
        desc = re.sub(r"\bqty[:\s]*\d+(?:[.,]\d+)?", "", body, flags=re.I)
        desc = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:pcs?|pieces?|ea|units?|un|nos?)\b",
                      "", desc, flags=re.I).strip(" ,;-")

        result.lines.append(
            ExtractedLine(
                raw_text=line,
                description=desc or body,
                quantity=qty or 1,
                size=parse_size(body),
                material=parse_material(body),
                notes=None if qty else "quantity not stated, assumed 1",
            )
        )

    if not result.lines:
        result.warnings.append("no line items found in the text")
    return result


def extract(rfq_text: str, use_llm: bool = True) -> ExtractionResult:
    if use_llm and os.getenv("ANTHROPIC_API_KEY"):
        try:
            return llm_extract(rfq_text)
        except Exception as exc:
            out = heuristic_extract(rfq_text)
            out.warnings.append(f"LLM extraction failed, fell back to heuristic: {exc}")
            return out
    return heuristic_extract(rfq_text)
