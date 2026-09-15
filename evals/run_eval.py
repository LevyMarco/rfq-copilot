#!/usr/bin/env python3
"""Run the golden set and print a scorecard.

    python evals/run_eval.py                 # heuristic baseline, no API key needed
    python evals/run_eval.py --llm           # with the LLM extractor
    python evals/run_eval.py --llm --compare # both, side by side

Four metrics, because they fail for different reasons and a single number
would hide which stage is broken:

  line_count   did we find the right number of products (extraction)
  sku          did we pick the right part           (matching)
  quantity     did we read the numbers right        (extraction)
  review       did we flag the lines a human must see, and only those
               (calibration - the metric nobody measures and everybody needs)

The last one is the important one. A system that is right 90% of the time and
cannot tell you *which* 90% is unusable in front of a customer.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.extract import extract  # noqa: E402
from app.match import match_all  # noqa: E402
from app.pricing import build_quote  # noqa: E402

CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))


@dataclass
class Tally:
    hit: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.total += 1
        self.hit += int(ok)

    @property
    def pct(self) -> float:
        return 100.0 * self.hit / self.total if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.hit}/{self.total} ({self.pct:.0f}%)"


@dataclass
class Report:
    label: str
    line_count: Tally = field(default_factory=Tally)
    sku: Tally = field(default_factory=Tally)
    quantity: Tally = field(default_factory=Tally)
    review: Tally = field(default_factory=Tally)
    failures: list[str] = field(default_factory=list)


def run(use_llm: bool, label: str) -> Report:
    rep = Report(label=label)

    for case in CASES:
        quote = build_quote(
            match_all(extract(case["text"], use_llm=use_llm).lines),
            customer_tier="standard",
        )
        got_skus = [l.sku for l in quote.lines]
        got_qty = [l.quantity for l in quote.lines]
        got_review = [l.needs_review for l in quote.lines]

        if "expect_line_count" in case:
            ok = len(quote.lines) == case["expect_line_count"]
            rep.line_count.add(ok)
            if not ok:
                rep.failures.append(
                    f"[{case['id']}] expected {case['expect_line_count']} lines, "
                    f"got {len(quote.lines)}"
                )

        for i, want in enumerate(case.get("expect_skus", [])):
            got = got_skus[i] if i < len(got_skus) else None
            rep.sku.add(got == want)
            if got != want:
                rep.failures.append(f"[{case['id']}] line {i+1}: wanted {want}, got {got}")

        for i, want in enumerate(case.get("expect_quantities", [])):
            got = got_qty[i] if i < len(got_qty) else None
            rep.quantity.add(got == want)
            if got != want:
                rep.failures.append(f"[{case['id']}] line {i+1}: qty wanted {want}, got {got}")

        for i, want in enumerate(case.get("expect_needs_review", [])):
            got = got_review[i] if i < len(got_review) else None
            rep.review.add(got == want)
            if got != want:
                rep.failures.append(
                    f"[{case['id']}] line {i+1}: needs_review wanted {want}, got {got}"
                )

    return rep


def print_report(rep: Report, verbose: bool) -> None:
    print(f"\n=== {rep.label} ===")
    print(f"  line count   {rep.line_count}")
    print(f"  sku match    {rep.sku}")
    print(f"  quantity     {rep.quantity}")
    print(f"  review flag  {rep.review}")
    if verbose and rep.failures:
        print(f"\n  {len(rep.failures)} failures:")
        for f in rep.failures:
            print(f"    - {f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use the LLM extractor")
    ap.add_argument("--compare", action="store_true", help="run both and compare")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every failure")
    args = ap.parse_args()

    print(f"Running {len(CASES)} cases from evals/cases.json")

    if args.compare:
        base = run(False, "heuristic baseline")
        llm = run(True, "LLM extractor")
        print_report(base, args.verbose)
        print_report(llm, args.verbose)
        delta = llm.sku.pct - base.sku.pct
        print(f"\n  LLM lift on SKU match: {delta:+.0f} percentage points")
    else:
        rep = run(args.llm, "LLM extractor" if args.llm else "heuristic baseline")
        print_report(rep, verbose=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
