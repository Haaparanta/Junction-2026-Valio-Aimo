"""Catalogue ETL (PLAN M2): hand-made records shaped like data/raw/products.json, built into a temporary catalog.db.

No real data is needed: every record here copies only the structure (and a few values) of the products the findings
cite: 464306 milk, 460013 ERP-only tomato, 464076 butter, 463233 portion butter, 466375 mozzarella and its substitutes.
"""

import json
import sqlite3

import pytest
from app.catalog import (
    allergen_status,
    build,
    content_for_unit,
    digital_link,
    get_product,
    get_record,
    gtin_check_ok,
    has_claim,
    json_ld,
    open_catalog,
    parse_name,
    reverse_term,
    reversed_tokens,
    summary_fields,
)
from app.contract import ProductSummary


def cls(name: str, values: list[dict]) -> dict:
    return {"type": "ENUM", "name": name, "values": values}


def product(
    pid: str,
    name_fi: str,
    *,
    sales: str = "ST",
    base: str = "ST",
    units: list[tuple[str, float, str | None]] | None = None,
    category: str = "10400",
    conversion: dict | None = None,
    contains: tuple[str, ...] = (),
    may_contain: tuple[str, ...] = (),
    free_from: tuple[str, ...] = (),
    claims: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
    gtin: str | None = None,
    sales_gtin: str | None = None,
    subs: tuple[str, ...] = (),
    tc: int | None = 4,
    minimal: bool = False,
    name_en: str | None = None,
    lactose: float | None = None,
) -> dict:
    units = units or [(sales, 1.0, sales_gtin)]
    p: dict = {
        "id": pid,
        "salesUnitGtin": sales_gtin,
        "salesUnit": sales,
        "baseUnit": base,
        "category": category,
        "allowedLotSize": 0.01,
        "deleted": False,
        "temperatureCondition": tc,
        "vendorName": "VALIO OY TUORE",
        "countryOfOrigin": "fi",
        "units": [{"unitId": u, "sizeInBaseUnits": s, **({"gtin": g} if g else {})} for u, s, g in units],
        "deposits": [],
    }
    if subs:
        p["substitutions"] = [{"product": pid, "substituteProduct": s} for s in subs]
    names = [{"value": name_fi, "language": "fi"}, {"value": name_en or name_fi, "language": "en"}]
    classifications = [
        cls("packagingMarkedLabel", [{"id": lb, "synkkaId": lb} for lb in labels] + [{"id": "coolTemperature"}]),
        cls(
            "allergen",
            [{"id": c, "unit": "CONTAINS"} for c in contains] + [{"id": c, "unit": "MAY_CONTAIN"} for c in may_contain],
        ),
        cls("nonAllergen", [{"id": c, "unit": "FREE_FROM"} for c in free_from]),
        cls("nutritionalClaim", [{"id": c, "synkkaId": c.split("_")[-1], "unit": "FREE_FROM"} for c in claims]),
    ]
    if minimal:
        p["synkkaData"] = {"names": names, "classifications": [cls(g["name"], []) for g in classifications]}
        return p
    p["synkkaData"] = {
        "gtin": gtin or sales_gtin or f"64000000{pid[:5]}",
        "names": names,
        "classifications": classifications,
        "brand": " Valio ",
        "producers": [{"id": "6408430000000", "name": "Valio Oy"}],
        "unitConversions": [conversion] if conversion else [],
        **(
            {"nutritionalContent": [{"id": "LACS", "value": lactose, "unit": "GRM", "basisQuantity": 100.0}]}
            if lactose is not None
            else {}
        ),
    }
    return p


def milk_conversion(litres: float = 1.0, grams: float = 1025.0) -> dict:
    return {
        "synkkaPackagingType": "BASE_UNIT_OR_EACH",
        "volume": {"unit": "LTR", "value": litres},
        "netWeight": {"unit": "GRM", "value": grams},
        "grossWeight": {"unit": "GRM", "value": grams + 27},
    }


def mozzarella(pid: str, name: str, *, claims: tuple[str, ...] = (), sales: str = "BAG", subs=()) -> dict:
    return product(
        pid,
        name,
        sales=sales,
        base=sales,
        category="10637",
        units=[(sales, 1.0, None), ("KI", 12.0, None)],
        conversion={
            "synkkaPackagingType": "BASE_UNIT_OR_EACH",
            "volume": {"unit": "GRM", "value": 125.0},
            "netWeight": {"unit": "GRM", "value": 210.0},
            "grossWeight": {"unit": "GRM", "value": 213.0},
        },
        contains=("AM",),
        claims=claims,
        gtin="8001868017584",
        subs=subs,
    )


PRODUCTS = [
    product(  # 464306: lactose-free milk drink, Finnish label, milk CONTAINS
        "464306",
        "Valio Hyvä suomalainen Arki® Eila® kevytmaitojuoma 1 l laktoositon",
        name_en="Valio Eila semi skimmed milk drink 1 l lactose free",
        units=[
            ("KRS", 160.0, None),
            ("PAL", 160.0, "6408430101016"),
            ("KI", 20.0, "6408430101009"),
            ("ST", 1.0, "6408430000487"),
        ],
        conversion=milk_conversion(),
        contains=("AM",),
        claims=("FREE_FROM_LACTOSE", "LOW_FAT", "VEGETARIAN"),
        labels=("GOODS_FROM_FINLAND_BLUE_SWAN",),
        sales_gtin="6408430000487",
        subs=("465039",),
        lactose=0.0,
    ),
    product(  # 465039: the milk's substitute, and it points back (a reciprocal pair)
        "465039",
        "Valio Eila® rasvaton maitojuoma 1 l laktoositon",
        units=[("ST", 1.0, "6408430000470")],
        conversion=milk_conversion(),
        contains=("AM",),
        claims=("FREE_FROM_LACTOSE",),
        sales_gtin="6408430000470",
        subs=("464306",),
    ),
    product(  # 460013: an ERP-only record (no synkka GTIN, names in capitals, nothing declared)
        "460013",
        "TOMAATTI COEUR DE BOEUF ES",
        sales="KG",
        base="KG",
        category="17401",
        tc=5,
        units=[("KG", 1.0, "2300100100000"), ("KI", 3.0, "2050000063077")],
        sales_gtin="2300100100000",
        minimal=True,
    ),
    product(  # 464076: name 4x5 kg per ST (KI = 4 ST), unitConversions 20 kg, Synkka GTIN on KI
        "464076",
        "Valio Eila® voi 4x5 kg laktoositon",
        category="10500",
        units=[("PAL", 160.0, None), ("KI", 4.0, "6408430030941"), ("ST", 1.0, "2050000070938")],
        conversion={
            "synkkaPackagingType": "BASE_UNIT_OR_EACH",
            "volume": {"unit": "GRM", "value": 20000.0},
            "netWeight": {"unit": "GRM", "value": 20000.0},
            "grossWeight": {"unit": "GRM", "value": 20100.0},
        },
        contains=("AM",),
        claims=("FREE_FROM_LACTOSE",),
        gtin="6408430030941",
        sales_gtin="2050000070938",
    ),
    product(  # 463233: portion butter sold per case; the name gives one 10 g portion
        "463233",
        "Valio voi 10 g normaalisuolainen",
        sales="KI",
        base="KI",
        category="10501",
        units=[("KI", 1.0, "6408430315055")],
        sales_gtin="6408430315055",
        gtin="6408430030286",
        conversion={"synkkaPackagingType": "CASE", "grossWeight": {"unit": "GRM", "value": 2348.0}},
        contains=("AM",),
        claims=("LOW_LACTOSE",),
    ),
    mozzarella(
        "466375",
        "Gran Castelli mozzarella 125g laktoositon",
        claims=("FREE_FROM_LACTOSE",),
        subs=("466151", "473986", "468526", "475908"),
    ),
    mozzarella("466151", "Pasta Filata Mozzarella 125g"),
    mozzarella("473986", "Galbani Mozzarella Laktoositon 100g", claims=("FREE_FROM_LACTOSE",), sales="ST"),
    mozzarella("468526", "Castelli mozzarella bufala 125g mozzarellajuusto puhvelinmaidosta"),
    mozzarella("475908", "Castelli mozzarella 125g"),
    product(  # gluten-free bread with gluten-free wheat starch (460124), and a substitute adding egg
        "460124",
        "Fria kuituleipä gluteeniton 300g",
        category="11000",
        contains=("UW",),
        may_contain=("AN",),
        free_from=("AE", "AW"),
        claims=("FREE_FROM_GLUTEN",),
        sales_gtin="7350011470014",
        subs=("460125",),
        conversion={"synkkaPackagingType": "BASE_UNIT_OR_EACH", "netWeight": {"unit": "GRM", "value": 300.0}},
    ),
    product(
        "460125",
        "Gluteeniton munaleipä 300g",
        category="11000",
        contains=("AE",),
        claims=("FREE_FROM_GLUTEN",),
        sales="PAK",
        base="PAK",
        conversion={"synkkaPackagingType": "BASE_UNIT_OR_EACH", "netWeight": {"unit": "GRM", "value": 300.0}},
    ),
    product(  # a lookalike the "maito" suffix must not find
        "466215",
        "Brunberg laktoositon maitosuklaa 100g",
        category="52000",
        contains=("AM",),
        claims=("FREE_FROM_LACTOSE",),
        tc=8,
    ),
    product("461000", "Jäätelö vanilja 2,5 l", category="41820", tc=7, contains=("AM",), subs=("461000",)),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("catalog")
    src = d / "products.json"
    src.write_text(json.dumps(PRODUCTS, ensure_ascii=False), encoding="utf-8")
    (d / "rel.csv").write_text("productId,deliveryReliability\n464306,1.0\n463233,0.0\n")
    (d / "carbon.csv").write_text("productId,AVG kg CO2-eq/kg\n464306,1.1\n466375,0.14500000000000002\n")
    db = d / "catalog.db"
    report = build(src, db, d / "rel.csv", d / "carbon.csv")
    conn = open_catalog(db)
    yield report, conn, d
    conn.close()


def rec(built, pid: str) -> dict:
    record = get_record(built[1], pid)
    assert record is not None
    return record


# ---- 2.1 streaming build ------------------------------------------------------------------------


def test_build_writes_every_product_in_wal_mode(built):
    report, conn, d = built
    assert report["products"] == len(PRODUCTS)
    assert report["kinds"] == {"full": len(PRODUCTS) - 1, "minimal": 1}
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == len(PRODUCTS)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert not (d / "catalog.db.building").exists()
    raw = conn.execute("SELECT record FROM products WHERE id = '464306'").fetchone()[0]
    assert "synkkaData" not in raw and "classifications" not in raw  # raw Synkka data never reaches the db
    assert report["seconds_total"] >= 0 and "peak_rss_mb" in report


def test_build_streams_instead_of_loading_the_whole_file(tmp_path, monkeypatch):
    src = tmp_path / "products.json"
    src.write_text(json.dumps(PRODUCTS[:3]), encoding="utf-8")

    def refuse(*_a, **_k):
        raise AssertionError("json.load must not read products.json")

    monkeypatch.setattr(json, "load", refuse)
    db = tmp_path / "catalog.db"
    assert build(src, db)["products"] == 3
    assert build(src, db)["products"] == 3  # a rebuild replaces the file in place
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 3


# ---- 2.2 allergens, claims and labels -----------------------------------------------------------


def test_lactose_free_milk_still_contains_milk(built):
    r = rec(built, "464306")
    assert "FREE_FROM_LACTOSE" in r["claims"]
    assert r["allergens"]["contains"] == ["AM"] and r["allergen_data"] == "declared"
    assert r["labels"] == ["GOODS_FROM_FINLAND_BLUE_SWAN"]  # the temperature label is not a quality label
    assert allergen_status(r, "AM") == "contains"
    assert allergen_status(r, "AE") == "not_listed"  # declared data without AE: not the same as free from
    assert has_claim(r, "FREE_FROM_LACTOSE") is True
    assert r["temperature_class"] == "chilled"


def test_erp_only_record_has_unknown_allergens(built):
    r = rec(built, "460013")
    assert r["kind"] == "minimal" and "minimal_record" in r["flags"]
    assert r["allergen_data"] == "unknown" and r["claim_data"] == "unknown"
    for code in ("AM", "AW", "AE"):
        assert allergen_status(r, code) == "unknown"  # never free from
    assert has_claim(r, "FREE_FROM_LACTOSE") is None
    assert built[1].execute("SELECT count(*) FROM allergens WHERE product_id = '460013'").fetchone()[0] == 0


def test_low_lactose_is_not_lactose_free(built):
    r = rec(built, "463233")
    assert has_claim(r, "FREE_FROM_LACTOSE") is False
    assert "low_lactose_not_lactose_free" in r["flags"]


def test_wheat_implies_gluten_and_beats_a_free_from(built):
    r = rec(built, "460124")
    assert r["allergens"]["implied_contains"] == ["AW"]
    assert r["allergens_contains"] == ["AW", "UW"]
    assert "AW" not in r["allergens"]["free_from"] and "AE" in r["allergens"]["free_from"]
    assert {"allergen_code_conflict", "gluten_free_with_gluten_cereal"} <= set(r["flags"])
    assert allergen_status(r, "AW") == "contains"
    assert allergen_status(r, "AN") == "may_contain"
    assert allergen_status(r, "AE") == "free_from"


# ---- 2.3 content per unit -----------------------------------------------------------------------


def test_milk_is_one_litre_per_piece(built):
    r = rec(built, "464306")
    c = r["content"]
    assert (c["unit"], c["value"], c["dim"], c["confidence"], c["needs_review"]) == ("ST", 1.0, "L", "high", False)
    assert c["static"]["source"] == "unit_conversions" and c["name"]["value"] == 1.0
    assert content_for_unit(r, "KI")["value"] == 20.0
    assert summary_fields(r)["content_per_unit"] == {"value": "1", "unit": "L", "source": "units", "confidence": "high"}


def test_butter_with_conflicting_sources_is_flagged(built):
    c = rec(built, "464076")["content"]
    assert c["static"]["value"] == 20.0 and c["name"]["value"] == 5.0  # unitConversions 20 kg, name 5 kg per ST
    assert c["confidence"] == "low" and c["needs_review"] is True
    assert "content_conflict" in c["flags"] and "unit_conversions_unit_ambiguous" in c["flags"]


def test_portion_butter_name_alone_is_low_confidence(built):
    c = rec(built, "463233")["content"]
    assert (c["value"], c["source"], c["confidence"]) == (0.01, "name", "low")
    assert "name_may_describe_one_item" in c["flags"]


def test_kilogram_unit_is_exact(built):
    c = rec(built, "460013")["content"]
    assert (c["value"], c["dim"], c["source"], c["confidence"]) == (1.0, "KG", "units", "high")
    assert content_for_unit(rec(built, "460013"), "KI")["value"] == 3.0


def test_mozzarella_uses_the_conversion_figure_that_matches_the_name(built):
    c = rec(built, "466375")["content"]
    assert (c["value"], c["dim"], c["confidence"]) == (0.125, "KG", "high")  # volume 125 g, not netWeight 210 g


@pytest.mark.parametrize(
    ("name", "value", "dim", "kind"),
    [
        ("Valio Eila® kevytmaitojuoma 1 l laktoositon", 1.0, "L", "single"),
        ("Arla Maitojuoma 1L laktoositon", 1.0, "L", "single"),
        ("Coca-Cola 12 x 1 l", 12.0, "L", "multipack"),
        ("Flora maidoton annosmargariini 70%, 200x10g", 2.0, "KG", "multipack"),
        ("Valio kevytmaitojuoma 2,5 dl UHT", 0.25, "L", "single"),
        ("Abba tonnikalaa vedessä 200/150g", 0.15, "KG", "drained"),
        ("Reuter & Stolt Cookie 96kpl 80g raaka pakaste", 7.68, "KG", "multipack"),
        ("Snellman Flank steak n2kg", 2.0, "KG", "single"),
        ("Kananmunat M90 luomu", 90.0, "PCS", "eggs"),
        ("Lautasliina 40 kpl", 40.0, "PCS", "count"),
    ],
)
def test_parse_name(name, value, dim, kind):
    p = parse_name(name)
    assert p is not None
    assert (round(p.value, 6), p.dim, p.kind) == (value, dim, kind)


def test_parse_name_without_a_size():
    assert parse_name("Valio Hyvä suomalainen 3,5 % maitojuoma") is None
    assert parse_name("Snellman Flank steak n2kg").approximate is True


# ---- 2.4 reliability and carbon -----------------------------------------------------------------


def test_signals_join_with_unknowns(built):
    report = built[0]
    milk, butter, moz, tomato = (rec(built, i) for i in ("464306", "463233", "466375", "460013"))
    assert milk["delivery_reliability"] == {"value": 1.0, "status": "known"}
    assert butter["delivery_reliability"]["value"] == 0.0 and "note" in butter["delivery_reliability"]
    assert tomato["delivery_reliability"] == {"value": None, "status": "unknown"}
    assert milk["carbon"]["kg_co2e_per_kg"] == 1.1 and milk["carbon"]["basis"] == "category_average"
    assert moz["carbon"]["kg_co2e_per_kg"] == 0.145  # float artefact removed
    assert tomato["carbon"]["status"] == "unknown"
    n = len(PRODUCTS)
    assert report["reliability"]["coverage_pct"] == round(100 * 2 / n, 1)
    assert report["carbon"]["coverage_pct"] == round(100 * 2 / n, 1)
    assert report["both_signals"] == 1 and report["neither_signal"] == n - 3


# ---- 2.5 substitution edges ---------------------------------------------------------------------


def test_mozzarella_substitutes_that_drop_lactose_free_are_tagged(built):
    subs = {s["product_id"]: s for s in rec(built, "466375")["substitutes"]}
    assert list(subs) == ["466151", "473986", "468526", "475908"]  # source order kept
    for pid in ("466151", "468526", "475908"):
        assert "drops_claim" in subs[pid]["risk"]
        assert subs[pid]["detail"]["dropped_claims"] == ["FREE_FROM_LACTOSE"]
    assert "drops_claim" not in subs["473986"]["risk"]
    assert subs["473986"]["risk"] == ["changes_unit"]  # BAG -> ST


def test_added_allergen_reciprocal_and_self_loop(built):
    bread = rec(built, "460124")["substitutes"][0]
    assert {"adds_allergen", "changes_unit"} <= set(bread["risk"])
    assert bread["detail"]["added_allergens"] == ["AE"]
    assert "drops_label" not in bread["risk"]
    milk = rec(built, "464306")["substitutes"]
    assert milk[0]["reciprocal"] is True and "drops_claim" in milk[0]["risk"]  # LOW_FAT, VEGETARIAN dropped
    assert rec(built, "461000")["substitutes"][0]["risk"] == ["self_loop"]
    assert built[0]["substitutions"]["edges"] == 8


# ---- 2.6 get_product and JSON-LD ----------------------------------------------------------------


def test_json_ld_has_gtin_and_digital_link(built):
    out = get_product(built[1], "464306")
    doc = out["json_ld"]
    assert doc["gtin"] == "06408430000487"
    assert doc["@id"] == "https://id.gs1.org/01/06408430000487" == digital_link("6408430000487")
    assert doc["sku"] == "464306" and doc["brand"]["name"] == "Valio"
    assert doc["gs1:netContent"] == {"@type": "gs1:QuantitativeValue", "gs1:value": 1.0, "gs1:unitCode": "LTR"}
    assert {
        "@type": "gs1:AllergenDetails",
        "gs1:allergenType": "gs1:AllergenTypeCode-AM",
        "gs1:allergenLevelOfContainmentCode": "gs1:LevelOfContainmentCode-CONTAINS",
    } in doc["gs1:hasAllergen"]
    assert "gs1:NutritionalClaimTypeCode-FREE_FROM_LACTOSE" in doc["gs1:nutritionalClaim"]
    carbon = next(p for p in doc["additionalProperty"] if p["propertyID"] == "carbonFootprint")
    assert "category average" in carbon["description"]
    ProductSummary(**summary_fields(out["record"]))  # the record fits the contract's summary


def test_json_ld_falls_back_from_an_in_store_gtin(built):
    doc = json_ld(rec(built, "464076"))  # sales-unit GTIN 2050000070938 is a restricted in-store code
    assert doc["gtin"] == "06408430030941"
    assert {"@type": "PropertyValue", "propertyID": "gtinUnit", "value": "KI"} in doc["additionalProperty"]


def test_json_ld_states_unknown_allergens(built):
    doc = json_ld(rec(built, "460013"))
    assert "@id" not in doc and "gtin" not in doc  # only 2-prefixed in-store codes
    assert "gs1:hasAllergen" not in doc
    assert {"@type": "PropertyValue", "propertyID": "allergenData", "value": "unknown"} in doc["additionalProperty"]


def test_get_product_unknown_id(built):
    assert get_product(built[1], "999999") is None


def test_gtin_check_digit():
    assert gtin_check_ok("6408430000487")
    assert not gtin_check_ok("6408430000488")
    assert not gtin_check_ok("64084300004") and not gtin_check_ok(None)


# ---- M4.1 search indexes ------------------------------------------------------------------------


def _fts(conn, query: str) -> set[str]:
    rows = conn.execute(
        "SELECT p.id FROM product_fts f JOIN products p ON p.num = f.rowid WHERE product_fts MATCH ?", (query,)
    ).fetchall()
    return {r[0] for r in rows}


def test_reversed_tokens_match_compound_ends(built):
    conn = built[1]
    assert reversed_tokens("Valio kevytmaitojuoma 1 l") == "oilav amoujotiamtyvek"
    assert _fts(conn, f'rev_fi:"{reverse_term("maitojuoma")}"*') == {"464306", "465039"}
    assert "466215" not in _fts(conn, f'rev_fi:"{reverse_term("maito")}"*')  # maitosuklaa ends in suklaa
    assert _fts(conn, f'rev_fi:"{reverse_term("mozzarella")}"*') >= {"466375", "466151"}


def test_fts_folds_diacritics_and_trigram_finds_substrings(built):
    conn = built[1]
    assert _fts(conn, "name_fi:jaatelo") == {"461000"} == _fts(conn, "name_fi:jäätelö")
    rows = conn.execute(
        "SELECT p.id FROM product_trigram t JOIN products p ON p.num = t.rowid WHERE product_trigram MATCH ?",
        ('"aitojuo"',),
    ).fetchall()
    assert {r[0] for r in rows} == {"464306", "465039"}
    tokens = conn.execute("SELECT name_tokens FROM products WHERE id = '464306'").fetchone()[0]
    assert tokens.split()[-3:] == ["1", "l", "laktoositon"]
