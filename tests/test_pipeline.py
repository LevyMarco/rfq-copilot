"""Unit tests for the parts that break silently.

The eval suite measures quality on realistic inputs. These tests pin the
behaviours that, when they regress, produce a plausible-looking wrong answer
instead of an error - which is the dangerous kind of bug in this system.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.catalog import parse_material, parse_quantity, parse_size, load_catalog
from app.extract import heuristic_extract
from app.match import match_line
from app.models import ExtractedLine
from app.pricing import build_quote, volume_discount


def test_size_aliases_collapse_to_one_form():
    for text in ['1/2"', "1/2 inch", "DN15", "0.5 in"]:
        assert parse_size(text) == '1/2"', text


def test_metric_thread_is_not_read_as_inches():
    assert parse_size("hex bolt M12x50") == "M12"


def test_material_longest_alias_wins():
    assert parse_material("stainless 316 valve") == "SS316"
    assert parse_material("stainless steel valve") == "SS304"


def test_quantity_formats():
    assert parse_quantity("qty 25 bolts") == 25
    assert parse_quantity("10 x ball valve") == 10
    assert parse_quantity("30 m hose") == 30
    assert parse_quantity("ball valve threaded") is None


def test_signature_block_is_not_a_line_item():
    text = (
        "Please quote:\n"
        '2 x Hydraulic Hose 1" 2-Wire Braid\n\n'
        "--\nJohn Miller | Maintenance Supervisor\n"
        "Northside Ltd | +1 555 0142\nSent from my iPhone"
    )
    assert len(heuristic_extract(text).lines) == 1


def test_size_conflict_beats_text_similarity():
    """A 2" valve must not win on a 1/2" request just because the words match."""
    line = ExtractedLine(raw_text='ball valve 1/2" SS316', description="ball valve", size='1/2"', material="SS316")
    best = match_line(line).candidates[0]
    sku = {p.sku: p for p in load_catalog()}[best.sku]
    assert sku.size == '1/2"' and sku.material == "SS316"


def test_unknown_product_is_flagged_not_guessed():
    line = ExtractedLine(raw_text="pneumatic actuator with limit switch box", description="pneumatic actuator")
    assert match_line(line).needs_review is True


def test_backorder_forces_review():
    line = ExtractedLine(raw_text="BV-9999", description="x", quantity=1)
    m = match_line(line)
    quote = build_quote([m])
    assert quote.lines[0].needs_review is True


def test_discount_is_capped():
    assert volume_discount(10_000) == 0.12
    quote = build_quote([], customer_tier="gold")
    assert quote.subtotal == 0
