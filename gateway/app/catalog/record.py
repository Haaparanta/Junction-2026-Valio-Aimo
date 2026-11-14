"""Reading catalog.db: the compact record and its schema.org / GS1 JSON-LD (PLAN M2.6).

`get_product(conn, id)` is what the get_product tool will call: the compact record (no raw synkkaData ever leaves
the build) and a JSON-LD view with the GTIN and a GS1 Digital Link. `summary_fields` maps the record onto the
contract's ProductSummary fields, so the route can build its response without knowing the record's layout.
"""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DIGITAL_LINK_BASE = "https://id.gs1.org/01/"
JSONLD_CONTEXT = {"@vocab": "https://schema.org/", "gs1": "https://ref.gs1.org/voc/"}
UNECE: dict[str, str] = {"L": "LTR", "KG": "KGM", "PCS": "H87"}
CARBON_NOTE = "category average (kg CO2e per kg), not measured for this product"  # D-11


def open_catalog(path: Path | str) -> sqlite3.Connection:
    """A read-only connection to a built catalog.db."""
    conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---- GTIN ----------------------------------------------------------------------------------------


def gtin_check_ok(gtin: str | None) -> bool:
    """GS1 mod-10 check digit for GTIN-8/12/13/14."""
    if not gtin or not gtin.isdigit() or len(gtin) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in gtin]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def gtin14(gtin: str) -> str:
    return gtin.zfill(14)


def restricted(gtin: str) -> bool:
    """Restricted-circulation numbers (GTIN-13 prefix 02 or 20-29): in-store codes, not global trade items."""
    g = gtin14(gtin)
    return g[1:3] == "02" or g[1] == "2"


def primary_gtin(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(gtin, unit it identifies): the sales unit's GTIN when it is a valid global one, else the Synkka GTIN."""
    for gtin in (record.get("sales_unit_gtin"), record.get("consumer_gtin")):
        if gtin and gtin_check_ok(gtin) and not restricted(gtin):
            unit = next((u["unit"] for u in record.get("units") or [] if u.get("gtin") == gtin), None)
            return gtin, unit
    return None, None


def digital_link(gtin: str) -> str:
    return DIGITAL_LINK_BASE + gtin14(gtin)


# ---- records -------------------------------------------------------------------------------------


def substitutes(conn: sqlite3.Connection, product_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT substitute_id, risk, detail, reciprocal FROM substitutions WHERE product_id = ? ORDER BY position",
        (product_id,),
    ).fetchall()
    return [
        {"product_id": r[0], "risk": json.loads(r[1]), "detail": json.loads(r[2]), "reciprocal": bool(r[3])}
        for r in rows
    ]


def get_record(conn: sqlite3.Connection, product_id: str) -> dict[str, Any] | None:
    """The compact record of one product, with its substitution candidates and their risk tags; None if absent."""
    row = conn.execute("SELECT record FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        return None
    record = json.loads(row[0])
    record["substitutes"] = substitutes(conn, product_id)
    return record


def content_for_unit(record: Mapping[str, Any], unit: str) -> dict[str, Any] | None:
    """Static content of any packaging level: per-base content x that unit's sizeInBaseUnits (for M3.5's vote)."""
    c = record.get("content") or {}
    if c.get("per_base") is None:
        return None
    size = next((u["size_in_base"] for u in record.get("units") or [] if u["unit"] == unit), None)
    if size is None:
        return None
    return {
        "unit": unit,
        "value": round(c["per_base"] * size, 6),
        "dim": c["dim"],
        "source": c["source"],
        "confidence": c["confidence"],
        "needs_review": c["needs_review"],
    }


def _num_str(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def content_per_unit(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """The contract's ContentPerUnit for the sales unit. unitConversions (GS1 packaging data) maps to 'units'."""
    c = record.get("content") or {}
    if c.get("value") is None:
        return None
    return {
        "value": _num_str(c["value"]),
        "unit": c["dim"],
        "source": "name" if c["source"] == "name" else "units",
        "confidence": c["confidence"],
    }


def summary_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """The contract's ProductSummary fields, ready for ProductSummary(**summary_fields(record))."""
    return {
        "product_id": record["product_id"],
        "name_fi": record["name_fi"],
        "name_en": record.get("name_en"),
        "brand": record.get("brand"),
        "vendor": record.get("vendor"),
        "category": record["category"],
        "sales_unit": record["sales_unit"],
        "content_per_unit": content_per_unit(record),
        "claims": record.get("claims") or [],
        "allergens_contains": record.get("allergens_contains") or [],
        "allergen_data": record.get("allergen_data") or "unknown",
        "temperature_class": record.get("temperature_class") or "unknown",
    }


# ---- JSON-LD -------------------------------------------------------------------------------------


def _names(record: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"@value": record[f"name_{lang}"], "@language": lang}
        for lang in ("fi", "sv", "en")
        if record.get(f"name_{lang}")
    ]


def json_ld(record: Mapping[str, Any]) -> dict[str, Any]:
    """schema.org Product with GS1 Web Vocabulary terms. Unknown allergen data is stated, never left to look safe."""
    doc: dict[str, Any] = {"@context": JSONLD_CONTEXT, "@type": "Product"}
    gtin, unit = primary_gtin(record)
    if gtin:
        doc["@id"] = digital_link(gtin)
        doc["gtin"] = gtin14(gtin)
        doc["gs1:gtin"] = gtin14(gtin)
    doc["sku"] = record["product_id"]
    doc["productID"] = record["product_id"]
    doc["name"] = _names(record)
    if record.get("brand"):
        doc["brand"] = {"@type": "Brand", "name": record["brand"]}
    if record.get("producer"):
        doc["manufacturer"] = {"@type": "Organization", "name": record["producer"]}
    doc["category"] = record["category"]
    if record.get("country_of_origin"):
        doc["countryOfOrigin"] = {"@type": "Country", "identifier": record["country_of_origin"].upper()}

    props: list[dict[str, Any]] = [
        {"@type": "PropertyValue", "propertyID": "salesUnit", "value": record["sales_unit"]},
        {"@type": "PropertyValue", "propertyID": "allergenData", "value": record.get("allergen_data", "unknown")},
    ]
    if gtin and unit:
        props.append({"@type": "PropertyValue", "propertyID": "gtinUnit", "value": unit})
    c = record.get("content") or {}
    if c.get("value") is not None:
        doc["gs1:netContent"] = {
            "@type": "gs1:QuantitativeValue",
            "gs1:value": c["value"],
            "gs1:unitCode": UNECE[c["dim"]],
        }
        props.append({"@type": "PropertyValue", "propertyID": "contentConfidence", "value": c["confidence"]})
    if record.get("allergen_data") == "declared":
        a = record.get("allergens") or {}
        details = [
            {
                "@type": "gs1:AllergenDetails",
                "gs1:allergenType": f"gs1:AllergenTypeCode-{code}",
                "gs1:allergenLevelOfContainmentCode": f"gs1:LevelOfContainmentCode-{level}",
            }
            for level, key in (("CONTAINS", "contains"), ("MAY_CONTAIN", "may_contain"), ("FREE_FROM", "free_from"))
            for code in a.get(key) or []
        ]
        if details:
            doc["gs1:hasAllergen"] = details
    if record.get("claims"):
        doc["gs1:nutritionalClaim"] = [f"gs1:NutritionalClaimTypeCode-{c}" for c in record["claims"]]
    if record.get("labels"):
        doc["gs1:packagingMarkedLabelAccreditation"] = [
            f"gs1:PackagingMarkedLabelAccreditationCode-{lb}" for lb in record["labels"]
        ]
    carbon = (record.get("carbon") or {}).get("kg_co2e_per_kg")
    if carbon is not None:
        props.append(
            {
                "@type": "PropertyValue",
                "propertyID": "carbonFootprint",
                "value": carbon,
                "unitText": "kg CO2e/kg",
                "description": CARBON_NOTE,
            }
        )
    reliability = (record.get("delivery_reliability") or {}).get("value")
    if reliability is not None:
        props.append({"@type": "PropertyValue", "propertyID": "deliveryReliability", "value": reliability})
    doc["additionalProperty"] = props
    return doc


def get_product(conn: sqlite3.Connection, product_id: str) -> dict[str, Any] | None:
    """{'record': compact record, 'json_ld': schema.org/GS1 JSON-LD}, or None for an unknown id."""
    record = get_record(conn, product_id)
    if record is None:
        return None
    return {"record": record, "json_ld": json_ld(record)}
