#!/usr/bin/env python3
"""Record Valio Aimo mock-API fixtures for replay mode (PLAN M3.2).

The snapshot's last cut-offs pass at Sun 15.11.2026 17:00 Helsinki, so record before then.

What it records, sequentially and at most 1,000 ids per call:
  * /price and /availability for the named demo and exception ids (PLAN §3, W-03, X-01..X-33)
    for requested dates 2026-11-16, 2026-11-15 (X-04), 2026-11-20 (X-05) and 2027-01-04 (X-16);
  * the same two endpoints for the whole catalogue (460000-477545) for 2026-11-16, so real
    search and offers (M4, M5) can run in replay mode after the cut-offs pass (skip with --no-catalog);
  * the malformed-id behaviour of X-19 and X-20, kept as separate raw calls.

Every raw response body is saved byte for byte with its SHA-256 in data/fixtures/manifest.json.
data/fixtures/ is git-ignored until the mentors allow committing it.

The key is read from VALIO_AIMO_API_KEY, or from a .env file in this checkout or the main
checkout (for git worktrees). It is never printed. Standard library only, so it runs anywhere:

    python3 scripts/record_fixtures.py            # everything
    python3 scripts/record_fixtures.py --no-catalog
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "fixtures"
BASE = os.environ.get("VALIO_AIMO_API_BASE_URL", "https://junction26.valioaimo.fi/api").rstrip("/")
CUSTOMER = "123"
MAX_IDS = 1000
MAIN_DATE = "2026-11-16"
EXTRA_DATES = ["2026-11-15", "2026-11-20", "2027-01-04"]  # X-04, X-05, X-16
CATALOG_RANGE = range(460000, 477546)  # 17,546 contiguous catalogue ids (A-07)

# Named groups, from docs/data-and-api-findings.md. Overlaps are fine: ids are deduplicated per call.
GROUPS: dict[str, list[str]] = {
    # W-03: the 29 genuine lactose-free milk options for the headline example.
    "w03_milk_options": [
        "464306", "464401", "464237", "463335", "464201", "464073", "464398", "463779", "469363",
        "462775", "463380", "463203", "469119", "469287", "464119", "465039", "476240", "463038",
        "469330", "469386", "466288", "462921", "464198", "464768", "465149", "462626", "464179",
        "464399", "464440",
    ],
    # W-01 exclusions and W-07 plant-drink variants.
    "w01_exclusions": ["469331", "472492", "476957", "477050", "469266", "473142", "463047",
                       "469541", "475534", "469457", "460032"],
    "w07_plant_drinks": ["468465", "474864", "464013"],
    # Demo step 6 (butter); the catalogue snapshot also covers every butter product.
    "demo_butter": ["463233", "463197"],
    "x01": ["463038", "469119", "464119", "465039"],
    "x02": ["474284", "468693", "466392", "462242", "476848"],
    "x03": ["466869", "464171"],
    "x04": ["464306", "464401", "463335"],
    "x05": ["463038", "464306"],
    "x07": ["464440", "460013", "461903", "470789"],
    "x08": ["463989", "464035", "469355", "470094", "477027", "467504"],
    "x09": ["461098", "473463", "469290", "474747"],
    "x10": ["469363", "462775", "463380", "469346"],
    "x11": ["460509", "470699", "468693"],
    "x12": ["464306", "463779", "461294"],
    "x13": ["462150", "462646"],
    "x14": ["465244", "477190", "468022", "460657"],
    "x15": ["460675"],
    "x16": ["464306", "463335", "464119"],
    "x17": ["461643", "476972", "462250", "475702"],
    "x18": ["464818"],
    "x19": ["461051"],
    "x21": ["463233", "463197"],
    "x22": ["464940", "463519"],
    "x23": ["476738", "469955", "464076"],
    "x24": ["463047", "469541", "460032"],
    "x25": ["464306", "468465", "474864"],
    "x26": ["466375", "466151", "468526", "475908", "473986", "465174", "465256", "463383"],
    "x27": ["468465", "470863", "469288", "470341", "473609", "464320"],
    "x28": ["460025", "460150", "471205", "473629"],
    "x29": ["469556", "469401", "464201", "464440", "469290", "465233"],
    "x30": ["470961", "460603", "460211", "467530", "467549"],
    "x31": ["464322", "470153"],
    "x32": ["463059", "463053", "466152", "473463", "463451"],
    "x33": ["471661"],
    # Other ids the findings cite (A-02, A-03, A-05, A-08, A-11, A-12, A-19).
    "doc_examples": ["460013", "460063", "463989", "460056", "463779", "463038", "465244", "461294",
                     "467042", "460635", "465987", "474449", "468648", "462321", "474880", "470434",
                     "460465", "461268", "461174", "460857", "461440", "465056", "467730", "471480",
                     "476936", "462629", "462762", "476525", "467204", "467157", "469402", "462395",
                     "465611"],
}
# X-19 deposit codes and X-20 malformed ids: recorded raw, never sent by the gateway client.
MALFORMED = ["999999", "460063 ", " 460063", "0460063", "477546", "459999", "abc", "4", "147"]


def find_key() -> str:
    key = os.environ.get("VALIO_AIMO_API_KEY", "").strip()
    if key:
        return key
    candidates = [REPO / ".env"]
    try:  # in a git worktree, the .env usually lives in the main checkout
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        candidates.append(Path(common).parent / ".env")
    except (OSError, subprocess.CalledProcessError):
        pass
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.removeprefix("export ").strip() == "VALIO_AIMO_API_KEY":
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
    sys.exit("VALIO_AIMO_API_KEY not found in the environment or in .env (the key is never printed).")


def request(method: str, path: str, key: str, body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": key, "Accept": "application/json", "User-Agent": "fixture-recorder/1"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(5):
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2**attempt)
                continue
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt < 4:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i : i + MAX_IDS] for i in range(0, len(ids), MAX_IDS)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-catalog", action="store_true", help="skip the full-catalogue snapshot")
    args = ap.parse_args()
    key = find_key()

    named = sorted({i for ids in GROUPS.values() for i in ids})
    plan: list[tuple[str, str, list[str]]] = []  # (set name, requested date, ids)
    for d in [MAIN_DATE, *EXTRA_DATES]:
        plan.append(("named", d, named))
    plan.append(("malformed", MAIN_DATE, MALFORMED))
    if not args.no_catalog:
        plan.append(("catalog", MAIN_DATE, [str(i) for i in CATALOG_RANGE]))

    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    files: list[dict] = []

    status, raw = request("GET", "/ping", key)
    (OUT / "ping.json").write_bytes(raw)
    files.append({"endpoint": "ping", "path": "ping.json", "http_status": status,
                  "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    if status != 200:
        sys.exit(f"/ping returned HTTP {status}; check the key and the base URL")

    for set_name, req_date, ids in plan:
        for endpoint in ("availability", "price"):
            for n, part in enumerate(chunks(ids)):
                body = {"customer": CUSTOMER, "requestedDate": req_date, "products": part}
                status, raw = request("POST", f"/{endpoint}", key, body)
                rel = Path("raw") / set_name / req_date / f"{endpoint}-{n:03d}.json"
                (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
                (OUT / rel).write_bytes(raw)
                time_now = None
                try:
                    time_now = json.loads(raw).get("timeNow")
                except (ValueError, AttributeError):
                    pass
                files.append({"set": set_name, "endpoint": endpoint, "requested_date": req_date,
                              "path": str(rel), "http_status": status, "ids": part,
                              "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                              "time_now": time_now, "request": {"customer": CUSTOMER,
                                                                "requestedDate": req_date}})
                print(f"{set_name:9} {req_date} {endpoint:12} chunk {n:2d}: HTTP {status}, "
                      f"{len(part):4d} ids, {len(raw):8d} bytes")
                if status != 200 and set_name != "malformed":
                    print(f"  warning: HTTP {status} for {rel}", file=sys.stderr)

    manifest = {
        "recorded_started_at": started,
        "recorded_finished_at": datetime.now(UTC).isoformat(),
        "base_url": BASE,
        "customer": CUSTOMER,
        "note": "Synthetic Junction 2026 challenge data; commit only if the mentors allow it.",
        "groups": GROUPS,
        "malformed_ids": MALFORMED,
        "files": files,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {len(files)} responses and data/fixtures/manifest.json")


if __name__ == "__main__":
    main()
