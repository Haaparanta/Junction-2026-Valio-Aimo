#!/usr/bin/env python3
"""Build data/catalog.db from the challenge files (PLAN M2.1).

    uv run python scripts/build_catalog.py                     # data/raw -> data/catalog.db
    uv run python scripts/build_catalog.py --json report.json  # also save the coverage report
    uv run python scripts/build_catalog.py --compare-prices data/fixtures/raw/catalog/2026-11-16

Prints the coverage report: products, content confidence, reliability and carbon coverage, substitution risk tags,
build time and peak memory. --compare-prices checks the static content against the API-implied content
(catalogPrice / comparisonPrice per the API unit, F-01) in recorded /price and /availability fixtures; it only reports,
the vote itself belongs to M3.5. Exit code 1 when the build misses the M2.1 budget (10 s, 100 MB).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "gateway")]

from app.catalog import build, content_for_unit, get_record  # noqa: E402

RAW = REPO / "data" / "raw"
BUDGET_S, BUDGET_MB = 10.0, 100.0


def compare_prices(db: Path, fixtures: Path) -> dict:
    """Agreement of the static content with the API-implied content, by confidence (within 2 % and 5 %)."""
    api_unit: dict[str, str] = {}
    for f in sorted(fixtures.glob("availability-*.json")):
        for p in json.loads(f.read_text()).get("products") or []:
            lines = p.get("scheduleLines") or []
            if lines and lines[0].get("salesUnit"):
                api_unit[p["productId"]] = lines[0]["salesUnit"]
    stats: dict[str, dict[str, int]] = {}
    conn = sqlite3.connect(db)
    for f in sorted(fixtures.glob("price-*.json")):
        for p in json.loads(f.read_text()).get("products") or []:
            cat, comp = (p.get("catalogPrice") or {}).get("value"), (p.get("comparisonPrice") or {}).get("value")
            dim = {"KG": "KG", "L": "L", "LTR": "L"}.get(p.get("comparisonUnit") or "")
            if not cat or not comp or not dim or p["productId"] not in api_unit:
                continue
            record = get_record(conn, p["productId"])
            static = content_for_unit(record, api_unit[p["productId"]]) if record else None
            conf = (static or {}).get("confidence") or "none"
            s = stats.setdefault(conf, {"compared": 0, "within_2pct": 0, "within_5pct": 0, "other_dim": 0})
            if static is None:
                continue
            if static["dim"] != dim:
                s["other_dim"] += 1
                continue
            api = cat / comp
            rel = abs(static["value"] - api) / max(static["value"], api)
            s["compared"] += 1
            s["within_2pct"] += rel <= 0.02
            s["within_5pct"] += rel <= 0.05
    conn.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", type=Path, default=RAW / "products.json")
    ap.add_argument("--reliability", type=Path, default=RAW / "delivery_reliability.csv")
    ap.add_argument("--carbon", type=Path, default=RAW / "carbon_footprint.csv")
    ap.add_argument("--out", type=Path, default=REPO / "data" / "catalog.db")
    ap.add_argument("--json", type=Path, help="write the report here as JSON")
    ap.add_argument("--compare-prices", type=Path, metavar="DIR", help="recorded price/availability fixtures")
    args = ap.parse_args()
    if not args.products.exists():
        print(f"missing {args.products}: run scripts/fetch_data.sh first", file=sys.stderr)
        return 2

    report = build(args.products, args.out, args.reliability, args.carbon)
    if args.compare_prices:
        report["api_content_agreement"] = compare_prices(args.out, args.compare_prices)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    over = report["seconds_total"] > BUDGET_S or (report["peak_rss_mb"] or 0) > BUDGET_MB
    print(
        f"\n{report['products']} products in {report['seconds_total']} s, peak RSS {report['peak_rss_mb']} MB, "
        f"{report['db_bytes'] / 1e6:.1f} MB -> {args.out}" + ("  OVER BUDGET" if over else ""),
        file=sys.stderr,
    )
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
