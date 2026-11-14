#!/usr/bin/env python3
"""Precision@10 of product search on the golden set (PLAN M4.5).

    uv run python scripts/eval_search.py                    # data/catalog.db, gateway/tests/golden_search.json
    uv run python scripts/eval_search.py --verbose          # also the top 10 of every query, misses marked
    uv run python scripts/eval_search.py --json report.json

Needs the real catalogue (scripts/build_catalog.py); never calls the Valio Aimo API. Exit code 1 when the mean
precision@10 is under the golden file's target (0.9) or any 'never' product appears in a result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "gateway")]

from app.catalog import open_catalog  # noqa: E402
from app.search import evaluate, search  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=REPO / "data" / "catalog.db")
    ap.add_argument("--golden", type=Path, default=REPO / "gateway" / "tests" / "golden_search.json")
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument("--verbose", action="store_true", help="print each query's top results")
    args = ap.parse_args()
    if not args.db.exists():
        print(f"no catalogue at {args.db}; run scripts/build_catalog.py first", file=sys.stderr)
        return 2

    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    conn = open_catalog(args.db)
    report = evaluate(conn, golden)
    target = float(golden.get("target_precision", 0.9))
    by_id = {q["id"]: q for q in golden["queries"]}

    for r in report["queries"]:
        p = "  -  " if r["precision"] is None else f"{r['precision']:.2f}"
        tag = " (held out)" if r["held_out"] else ""
        never = f"  NEVER: {','.join(r['never_seen'])}" if r["never_seen"] else ""
        print(f"{p}  {r['id']:<44} {r['returned']:>2}/{r['total_matches']:<4} {r['ms']:>6.1f} ms{tag}{never}")
        if args.verbose:
            q = by_id[r["id"]]
            relevant = set(q["relevant"])
            for h in search(conn, **{**q["args"], "limit": report["k"]}).hits:
                mark = "+" if h.product_id in relevant else "-"
                print(f"        {mark} {h.product_id} {h.record['name_fi']}")
    print()
    print(f"precision@{report['k']}: {report['precision']:.3f} (target {target})")
    print(f"  tuned {report['precision_tuned']}, held out {report['precision_held_out']}")
    print(f"  fi {report['precision_fi']}, en {report['precision_en']}")
    print(f"never violations: {report['never_violations']}")
    print(f"latency p50 {report['ms_p50']} ms, max {report['ms_max']} ms")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = report["precision"] is not None and report["precision"] >= target and report["never_violations"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
