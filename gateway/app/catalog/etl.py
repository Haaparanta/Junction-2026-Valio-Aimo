"""Catalogue ETL: data/raw/products.json -> data/catalog.db (PLAN M2.1-M2.5, M4.1 indexes).

The 87 MB array is streamed with ijson, one product at a time (json.load would hold about 600 MB), and written in
batches into a fresh SQLite file that replaces the old one only when the build has finished. Raw synkkaData never
reaches the database: each product becomes one compact JSON record plus the columns and child tables search filters on.

Tables (see SCHEMA): products, units, allergens, claims, labels, substitutions, meta, and the M4 indexes product_fts
(FTS5, unicode61 remove_diacritics 2, with a reversed-token column for Finnish compound ends) and product_trigram.
"""

import csv
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ijson

from . import codes, text
from .content import static_content
from .record import CARBON_NOTE

SCHEMA_VERSION = "1"
BATCH = 500
INSERT_PRODUCT = "INSERT INTO products VALUES (?" + ",?" * 33 + ")"  # noqa: S608 - 34 placeholders, no input

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE products (
  num INTEGER PRIMARY KEY,            -- int(id): the rowid the FTS tables join on
  id TEXT NOT NULL UNIQUE,            -- six-digit product code used by every API and CSV
  kind TEXT NOT NULL,                 -- 'full' (GS1 Synkka record) or 'minimal' (ERP-only record, D-02)
  name_fi TEXT NOT NULL, name_sv TEXT, name_en TEXT,
  name_tokens TEXT NOT NULL,          -- casefolded fi word tokens, space-separated (whole-word checks)
  brand TEXT, vendor TEXT, producer TEXT,
  category TEXT NOT NULL,
  sales_unit TEXT NOT NULL, base_unit TEXT NOT NULL, allowed_lot_size REAL,
  sales_unit_gtin TEXT, consumer_gtin TEXT,
  country TEXT,
  temperature_condition INTEGER, temperature_class TEXT NOT NULL,
  variable_unit INTEGER NOT NULL,
  allergen_data TEXT NOT NULL,        -- 'declared' or 'unknown'; unknown never means free from
  claim_data TEXT NOT NULL,
  lactose_g_per_100 REAL,
  content_value REAL, content_dim TEXT, content_source TEXT, content_confidence TEXT,
  content_needs_review INTEGER NOT NULL,
  content_per_base REAL,
  reliability REAL,                   -- delivery_reliability.csv; NULL = unknown
  carbon_kg_per_kg REAL,              -- carbon_footprint.csv (category average); NULL = unknown
  placeholder INTEGER NOT NULL,       -- 465611 NAYTE-style junk, filtered from cheapest-first lists
  flags TEXT NOT NULL,                -- JSON array of data-quality flags
  record TEXT NOT NULL                -- the compact record (JSON) that get_product returns
);
CREATE INDEX products_category ON products(category);

CREATE TABLE units (
  product_id TEXT NOT NULL, unit TEXT NOT NULL, size_in_base REAL NOT NULL, gtin TEXT,
  content_value REAL,                 -- static content of this level (per-base content x size), for M3.5
  PRIMARY KEY (product_id, unit)
) WITHOUT ROWID;

CREATE TABLE allergens (
  product_id TEXT NOT NULL, code TEXT NOT NULL,
  level TEXT NOT NULL,                -- CONTAINS, MAY_CONTAIN, UNDECLARED, FREE_FROM or IMPLIED (AW from UW)
  PRIMARY KEY (product_id, code, level)
) WITHOUT ROWID;
CREATE INDEX allergens_code ON allergens(code, level);

CREATE TABLE claims (product_id TEXT NOT NULL, code TEXT NOT NULL, PRIMARY KEY (product_id, code)) WITHOUT ROWID;
CREATE INDEX claims_code ON claims(code);
CREATE TABLE labels (product_id TEXT NOT NULL, code TEXT NOT NULL, PRIMARY KEY (product_id, code)) WITHOUT ROWID;
CREATE INDEX labels_code ON labels(code);

CREATE TABLE substitutions (
  product_id TEXT NOT NULL, substitute_id TEXT NOT NULL,
  position INTEGER NOT NULL,          -- order in the source list (may or may not be a priority, D-12)
  reciprocal INTEGER NOT NULL, self_loop INTEGER NOT NULL,
  risk TEXT NOT NULL,                 -- JSON array: drops_claim, drops_label, adds_allergen, allergens_unknown,
                                      --             changes_unit, changes_category, self_loop
  detail TEXT NOT NULL,               -- JSON object: which claims, labels and allergens, the two units
  PRIMARY KEY (product_id, substitute_id)
) WITHOUT ROWID;
CREATE INDEX substitutions_substitute ON substitutions(substitute_id);

CREATE VIRTUAL TABLE product_fts USING fts5(
  name_fi, name_sv, name_en, brand, rev_fi,
  tokenize = 'unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE product_trigram USING fts5(names, tokenize = 'trigram remove_diacritics 1');
"""

_WS = re.compile(r"\s+")


def _clean(s: Any) -> str | None:
    if not isinstance(s, str):
        return None
    s = _WS.sub(" ", s).strip()
    return s or None


@dataclass
class Signals:
    reliability: dict[str, float] = field(default_factory=dict)
    carbon: dict[str, float] = field(default_factory=dict)
    reliability_rows: int = 0
    carbon_rows: int = 0


def _read_csv(path: Path | None) -> tuple[dict[str, float], int]:
    if path is None or not Path(path).exists():
        return {}, 0
    out: dict[str, float] = {}
    rows = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            rows += 1
            try:
                out[row[0].strip()] = float(row[1])
            except ValueError:
                continue
    return out, rows


def load_signals(reliability_csv: Path | None, carbon_csv: Path | None) -> Signals:
    rel, rel_rows = _read_csv(reliability_csv)
    # 795 carbon rows carry float artefacts (0.14500000000000002); 3 decimals keep real values such as 4.975.
    carb, carb_rows = _read_csv(carbon_csv)
    return Signals(rel, {k: round(v, 3) for k, v in carb.items()}, rel_rows, carb_rows)


def iter_products(path: Path | str) -> Iterator[dict[str, Any]]:
    """Stream the products array one dict at a time."""
    with open(path, "rb") as f:
        yield from ijson.items(f, "item", use_float=True)


# ---- one product ---------------------------------------------------------------------------------


def _names(synkka: Mapping[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {"fi": None, "sv": None, "en": None}
    for n in synkka.get("names") or []:
        lang = n.get("language")
        if lang in out and out[lang] is None:
            out[lang] = _clean(n.get("value"))
    return out


def _flags_from_names(name_fi: str, claims: Iterable[str]) -> list[str]:
    flags: list[str] = []
    low = name_fi.casefold()
    claims = set(claims)
    if "laktoositon" in low and "FREE_FROM_LACTOSE" not in claims:
        flags.append("name_says_lactose_free_without_claim")  # 17 products (D-13); the claim wins
    if "vähälaktoosinen" in low and "FREE_FROM_LACTOSE" in claims:
        flags.append("name_says_low_lactose_with_lactose_free_claim")  # 462234
    return flags


def transform(p: Mapping[str, Any], signals: Signals) -> dict[str, Any]:
    """One raw product -> the compact record (a plain dict), without substitution candidates."""
    pid = str(p["id"]).strip()
    synkka = p.get("synkkaData") or {}
    names = _names(synkka)
    name_fi = names["fi"] or names["en"] or names["sv"] or pid
    dec = codes.decode(synkka)
    content = static_content(p, name_fi)
    kind = "full" if synkka.get("gtin") else "minimal"
    tc = p.get("temperatureCondition")
    tclass = codes.temperature_class(tc)

    flags = list(dec.flags) + _flags_from_names(name_fi, dec.claims) + content.flags
    if kind == "minimal":
        flags.append("minimal_record")
    if "LOW_LACTOSE" in dec.claims and "FREE_FROM_LACTOSE" not in dec.claims:
        flags.append("low_lactose_not_lactose_free")
    if tclass == "unknown":
        flags.append("temperature_unknown")
    elif dec.temperature_label and dec.temperature_label != tclass:
        flags.append("temperature_label_mismatch")  # 463989: code 3 but text says frozen
    placeholder = name_fi.strip().upper() in {"NÄYTE", "NAYTE"}
    if placeholder:
        flags.append("placeholder_product")

    units = []
    for u in p.get("units") or []:
        uid, size = u.get("unitId"), u.get("sizeInBaseUnits")
        if not uid or not isinstance(size, int | float) or any(x["unit"] == uid for x in units):
            continue
        units.append(
            {
                "unit": uid,
                "size_in_base": float(size),
                "gtin": u.get("gtin"),
                "content": round(content.per_base * size, 6) if content.per_base is not None else None,
            }
        )

    rel = signals.reliability.get(pid)
    carbon = signals.carbon.get(pid)
    producers = synkka.get("producers") or []
    record: dict[str, Any] = {
        "product_id": pid,
        "kind": kind,
        "name_fi": name_fi,
        "name_sv": names["sv"],
        "name_en": names["en"],
        "brand": _clean(synkka.get("brand")),
        "vendor": _clean(p.get("vendorName")),
        "producer": _clean(producers[0].get("name")) if producers else None,
        "category": str(p.get("category") or ""),
        "sales_unit": p.get("salesUnit") or "",
        "base_unit": p.get("baseUnit") or "",
        "allowed_lot_size": p.get("allowedLotSize"),
        "units": units,
        "sales_unit_gtin": p.get("salesUnitGtin"),
        "consumer_gtin": synkka.get("gtin"),
        "country_of_origin": (p.get("countryOfOrigin") or None),
        "temperature_condition": tc,
        "temperature_class": tclass,
        "min_temperature": synkka.get("minTemperature"),
        "max_temperature": synkka.get("maxTemperature"),
        "variable_unit": bool(synkka.get("variableUnit")),
        "claims": dec.claims,
        "claim_data": dec.claim_data,
        "labels": dec.labels,
        "allergen_data": dec.allergen_data,
        "allergens": dec.allergens_dict(),
        "allergens_contains": dec.contains_effective,
        "lactose_g_per_100": dec.lactose_g_per_100,
        "content": content.as_dict(),
        "delivery_reliability": {
            "value": rel,
            "status": "known" if rel is not None else "unknown",
            **({"note": "0.0 may mean no deliveries measured (Q-13)"} if rel == 0.0 else {}),
        },
        "carbon": {
            "kg_co2e_per_kg": carbon,
            "status": "known" if carbon is not None else "unknown",
            "basis": "category_average",  # D-11: not measured per product; CARBON_NOTE has the wording
        },
        "deposits": [d for d in p.get("deposits") or [] if isinstance(d, dict)],
        "placeholder": placeholder,
        "flags": sorted(set(flags)),
    }
    return record


# ---- the build -----------------------------------------------------------------------------------


@dataclass
class _Batch:
    products: list[tuple] = field(default_factory=list)
    units: list[tuple] = field(default_factory=list)
    allergens: list[tuple] = field(default_factory=list)
    claims: list[tuple] = field(default_factory=list)
    labels: list[tuple] = field(default_factory=list)
    fts: list[tuple] = field(default_factory=list)
    trigram: list[tuple] = field(default_factory=list)

    def flush(self, conn: sqlite3.Connection) -> None:
        conn.executemany(INSERT_PRODUCT, self.products)
        conn.executemany("INSERT OR IGNORE INTO units VALUES (?,?,?,?,?)", self.units)
        conn.executemany("INSERT OR IGNORE INTO allergens VALUES (?,?,?)", self.allergens)
        conn.executemany("INSERT OR IGNORE INTO claims VALUES (?,?)", self.claims)
        conn.executemany("INSERT OR IGNORE INTO labels VALUES (?,?)", self.labels)
        conn.executemany(
            "INSERT INTO product_fts(rowid, name_fi, name_sv, name_en, brand, rev_fi) VALUES (?,?,?,?,?,?)", self.fts
        )
        conn.executemany("INSERT INTO product_trigram(rowid, names) VALUES (?,?)", self.trigram)
        for lst in (self.products, self.units, self.allergens, self.claims, self.labels, self.fts, self.trigram):
            lst.clear()

    def __len__(self) -> int:
        return len(self.products)


def _add(batch: _Batch, r: dict[str, Any]) -> None:
    pid, c = r["product_id"], r["content"]
    num = int(pid) if pid.isdigit() else None
    batch.products.append(
        (
            num,
            pid,
            r["kind"],
            r["name_fi"],
            r["name_sv"],
            r["name_en"],
            text.name_tokens(r["name_fi"]),
            r["brand"],
            r["vendor"],
            r["producer"],
            r["category"],
            r["sales_unit"],
            r["base_unit"],
            r["allowed_lot_size"],
            r["sales_unit_gtin"],
            r["consumer_gtin"],
            r["country_of_origin"],
            r["temperature_condition"],
            r["temperature_class"],
            int(r["variable_unit"]),
            r["allergen_data"],
            r["claim_data"],
            r["lactose_g_per_100"],
            c["value"],
            c["dim"],
            c["source"],
            c["confidence"],
            int(c["needs_review"]),
            c["per_base"],
            r["delivery_reliability"]["value"],
            r["carbon"]["kg_co2e_per_kg"],
            int(r["placeholder"]),
            json.dumps(r["flags"]),
            json.dumps(r, ensure_ascii=False, separators=(",", ":")),
        )
    )
    for u in r["units"]:
        batch.units.append((pid, u["unit"], u["size_in_base"], u["gtin"], u["content"]))
    a = r["allergens"]
    for level, key in (
        ("CONTAINS", "contains"),
        ("MAY_CONTAIN", "may_contain"),
        ("UNDECLARED", "undeclared"),
        ("FREE_FROM", "free_from"),
        ("IMPLIED", "implied_contains"),
    ):
        batch.allergens.extend((pid, code, level) for code in a[key])
    batch.claims.extend((pid, code) for code in r["claims"])
    batch.labels.extend((pid, code) for code in r["labels"])
    if num is not None:
        batch.fts.append(
            (num, r["name_fi"], r["name_sv"], r["name_en"], r["brand"], text.reversed_tokens(r["name_fi"]))
        )
        names = " | ".join(x for x in (r["name_fi"], r["name_sv"], r["name_en"], r["brand"]) if x)
        batch.trigram.append((num, names))


def _risk(orig: Mapping[str, Any], sub: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Risk tags of one substitution rule (D-12). Rules are hints: every tag is something M11 must re-check."""
    tags: list[str] = []
    detail: dict[str, Any] = {}
    dropped = sorted(set(orig["claims"]) - set(sub["claims"]))
    if dropped:
        tags.append("drops_claim")
        detail["dropped_claims"] = dropped
        if sub["claim_data"] == "unknown":
            detail["substitute_claim_data"] = "unknown"
    dropped_labels = sorted(set(orig["labels"]) - set(sub["labels"]))
    if dropped_labels:
        tags.append("drops_label")
        detail["dropped_labels"] = dropped_labels
    if sub["allergen_data"] == "unknown" and orig["allergen_data"] == "declared":
        tags.append("allergens_unknown")
    elif sub["allergen_data"] == "declared":
        added = sorted(set(sub["contains"]) - set(orig["contains"]))
        if added and orig["allergen_data"] == "declared":
            tags.append("adds_allergen")
            detail["added_allergens"] = added
        elif added:
            detail["substitute_allergens"] = added  # the original declares nothing, so nothing is "added" for sure
    if orig["sales_unit"] != sub["sales_unit"]:
        tags.append("changes_unit")
    detail["units"] = [orig["sales_unit"], sub["sales_unit"]]
    if orig["category"] != sub["category"]:
        tags.append("changes_category")
        detail["categories"] = [orig["category"], sub["category"]]
    return tags, detail


def _facts(conn: sqlite3.Connection, ids: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pid in ids:
        row = conn.execute("SELECT record FROM products WHERE id = ?", (pid,)).fetchone()
        if row is None:
            continue
        r = json.loads(row[0])
        out[pid] = {
            "claims": r["claims"],
            "claim_data": r["claim_data"],
            "labels": r["labels"],
            "allergen_data": r["allergen_data"],
            "contains": r["allergens_contains"],
            "sales_unit": r["sales_unit"],
            "category": r["category"],
        }
    return out


def _build_substitutions(conn: sqlite3.Connection, rules: list[tuple[str, str, int]]) -> dict[str, int]:
    pairs = {(a, b) for a, b, _ in rules}
    facts = _facts(conn, {x for a, b, _ in rules for x in (a, b)})
    rows = []
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for a, b, pos in rules:
        if (a, b) in seen or a not in facts or b not in facts:
            continue
        seen.add((a, b))
        self_loop = a == b
        tags, detail = ([], {}) if self_loop else _risk(facts[a], facts[b])
        if self_loop:
            tags = ["self_loop"]
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
        rows.append(
            (a, b, pos, int((b, a) in pairs and not self_loop), int(self_loop), json.dumps(tags), json.dumps(detail))
        )
    conn.executemany("INSERT INTO substitutions VALUES (?,?,?,?,?,?,?)", rows)
    counts["edges"] = len(rows)
    counts["products_with_rules"] = len({a for a, *_ in rows})
    risky = {"drops_claim", "drops_label", "adds_allergen"}
    counts["drops_claim_label_or_adds_allergen"] = sum(1 for r in rows if risky & set(json.loads(r[5])))
    return counts


def _peak_rss_mb() -> float | None:
    try:
        import resource
        import sys

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024, 1)
    except Exception:  # noqa: BLE001 - not available everywhere; the number is a report, not a result
        return None


def build(
    products_json: Path | str,
    out_db: Path | str,
    reliability_csv: Path | str | None = None,
    carbon_csv: Path | str | None = None,
) -> dict[str, Any]:
    """Build catalog.db from the raw files and return the coverage report. The old file is replaced atomically."""
    t0 = time.perf_counter()
    out_db = Path(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_db.with_name(out_db.name + ".building")
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)
    signals = load_signals(Path(reliability_csv) if reliability_csv else None, Path(carbon_csv) if carbon_csv else None)

    conn = sqlite3.connect(tmp)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(SCHEMA)

    n = 0
    kinds: dict[str, int] = {}
    conf: dict[str, int] = {}
    sources: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    allergen_declared = rel_hits = carbon_hits = both = neither = needs_review = 0
    seen_ids: set[str] = set()
    duplicates = 0
    rules: list[tuple[str, str, int]] = []
    batch = _Batch()
    conn.execute("BEGIN")
    for p in iter_products(products_json):
        pid = str(p.get("id", "")).strip()
        if not pid or pid in seen_ids or p.get("deleted"):
            duplicates += bool(pid in seen_ids)
            continue
        seen_ids.add(pid)
        r = transform(p, signals)
        _add(batch, r)
        for i, s in enumerate(p.get("substitutions") or []):
            sub = str(s.get("substituteProduct") or "").strip()
            if sub:
                rules.append((pid, sub, i))
        n += 1
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        c = r["content"]
        conf[c["confidence"] or "none"] = conf.get(c["confidence"] or "none", 0) + 1
        sources[c["source"] or "none"] = sources.get(c["source"] or "none", 0) + 1
        needs_review += c["needs_review"]
        allergen_declared += r["allergen_data"] == "declared"
        has_rel = r["delivery_reliability"]["value"] is not None
        has_carbon = r["carbon"]["kg_co2e_per_kg"] is not None
        rel_hits += has_rel
        carbon_hits += has_carbon
        both += has_rel and has_carbon
        neither += not has_rel and not has_carbon
        for f in r["flags"]:
            flag_counts[f] = flag_counts.get(f, 0) + 1
        if len(batch) >= BATCH:
            batch.flush(conn)
    batch.flush(conn)
    t_stream = time.perf_counter() - t0

    subs = _build_substitutions(conn, rules)
    conn.execute("INSERT INTO product_fts(product_fts) VALUES ('optimize')")
    conn.execute("INSERT INTO product_trigram(product_trigram) VALUES ('optimize')")

    def pct(k: int) -> float:
        return round(100 * k / n, 1) if n else 0.0

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "products": n,
        "kinds": kinds,
        "duplicates_skipped": duplicates,
        "allergen_data_declared": allergen_declared,
        "allergen_data_unknown": n - allergen_declared,
        "content": {
            "by_confidence": conf,
            "by_source": sources,
            "needs_review": needs_review,
            "with_value_pct": pct(n - conf.get("none", 0)),
        },
        "reliability": {
            "csv_rows": signals.reliability_rows,
            "matched": rel_hits,
            "coverage_pct": pct(rel_hits),
            "csv_ids_not_in_catalog": len(set(signals.reliability) - seen_ids),
        },
        "carbon": {
            "csv_rows": signals.carbon_rows,
            "matched": carbon_hits,
            "coverage_pct": pct(carbon_hits),
            "csv_ids_not_in_catalog": len(set(signals.carbon) - seen_ids),
            "note": CARBON_NOTE,
        },
        "both_signals": both,
        "neither_signal": neither,
        "substitutions": subs,
        "flags": dict(sorted(flag_counts.items(), key=lambda kv: -kv[1])),
        "seconds_stream": round(t_stream, 2),
    }
    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [
            ("schema_version", SCHEMA_VERSION),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S%z")),
            ("source_bytes", str(os.path.getsize(products_json))),
            ("report", json.dumps(report)),
        ],
    )
    conn.commit()
    conn.execute("ANALYZE")
    conn.execute("VACUUM")
    conn.execute("PRAGMA journal_mode = WAL")  # persisted in the file: readers and a rebuild do not block each other
    conn.close()
    for suffix in ("-wal", "-shm"):
        Path(str(out_db) + suffix).unlink(missing_ok=True)
    os.replace(tmp, out_db)
    report["seconds_total"] = round(time.perf_counter() - t0, 2)
    report["peak_rss_mb"] = _peak_rss_mb()
    report["db_bytes"] = out_db.stat().st_size
    return report
