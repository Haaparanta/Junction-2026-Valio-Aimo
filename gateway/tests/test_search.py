"""Product search (PLAN M4) over a tiny catalog.db built in the test with the M2 builder.

The records copy only the shape of products the findings cite (S-02, S-04, X-24, X-27): lactose-free milks and their
lookalikes (milk chocolate, ice cream, coffee milk, low-lactose milk), butter and peanut butter, salmon and rainbow
trout, gluten-free bread with wheat starch, oat drinks with and without gluten. No real data, no Valio Aimo API.
The golden set itself (M4.5) runs against the real catalogue only when data/catalog.db exists.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from app import search as search_mod
from app.catalog import build, open_catalog
from app.contract import ProductSummary
from app.search import evaluate, head_match_expr, match_head, parse_heads, quote, search

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).with_name("golden_search.json")


def cls(name: str, values: list[dict]) -> dict:
    return {"type": "ENUM", "name": name, "values": values}


def product(
    pid: str,
    name_fi: str,
    *,
    category: str = "10400",
    contains: tuple[str, ...] = (),
    may_contain: tuple[str, ...] = (),
    claims: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
    tc: int | None = 4,
    minimal: bool = False,
    name_en: str | None = None,
) -> dict:
    names = [{"value": name_fi, "language": "fi"}] + ([{"value": name_en, "language": "en"}] if name_en else [])
    groups = [
        cls("packagingMarkedLabel", [{"id": lb} for lb in labels]),
        cls(
            "allergen",
            [{"id": c, "unit": "CONTAINS"} for c in contains] + [{"id": c, "unit": "MAY_CONTAIN"} for c in may_contain],
        ),
        # Every full record here declares something, so its allergen data is 'declared' (X99 if nothing else).
        cls("nonAllergen", [] if contains or may_contain else [{"id": "X99", "unit": "FREE_FROM"}]),
        cls("nutritionalClaim", [{"id": c, "unit": "FREE_FROM"} for c in claims]),
    ]
    p: dict = {
        "id": pid,
        "salesUnit": "ST",
        "baseUnit": "ST",
        "category": category,
        "allowedLotSize": 1,
        "deleted": False,
        "temperatureCondition": tc,
        "vendorName": "TEST OY",
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1.0}],
        "deposits": [],
    }
    if minimal:
        p["synkkaData"] = {"names": names, "classifications": []}
    else:
        p["synkkaData"] = {"gtin": f"64000000{pid[:5]}", "names": names, "classifications": groups}
    return p


LF = ("FREE_FROM_LACTOSE",)
GF = ("FREE_FROM_GLUTEN",)
PRODUCTS = [
    # milk (S-02, S-03, X-24)
    product(
        "464306",
        "Valio Eila kevytmaitojuoma 1 l laktoositon",
        contains=("AM",),
        claims=LF,
        name_en="Valio Eila semi skimmed milk drink 1 l lactose free",
    ),
    product("464201", "Valio kevytmaito 1 l laktoositon UHT", contains=("AM",), claims=LF),
    product("464119", "Valio rasvaton maito 1 l laktoositon UHT", contains=("AM",), claims=LF),
    product("464237", "Valio kahvimaito 1 l laktoositon UHT", contains=("AM",), claims=LF),
    product("463047", "Arla Täysmaito 1 L vähälaktoosinen UHT", contains=("AM", "ML"), claims=("LOW_LACTOSE",)),
    product("466215", "Brunberg Laktoositon maitosuklaa 150 g", category="52201", contains=("AM",), claims=LF),
    product("461000", "Laktoositon maitojäätelö vanilja 2,5 l", category="41820", tc=7, contains=("AM",), claims=LF),
    product("462000", "Maito-suklaajuoma 1 l laktoositon", category="22540", contains=("AM",), claims=LF),
    product("468000", "Oatly kaurajuoma 1 l", category="10402", contains=("GO", "AW"), claims=("VEGAN",)),
    product(
        "468465", "Oddlygood kaurajuoma 1 l UHT gluteeniton", category="10402", contains=("GO",), claims=("VEGAN", *GF)
    ),
    product("468466", "Alpro soijajuoma 1 l", category="10402", claims=("VEGAN",)),
    # butter (S-04)
    product("463798", "Valio voi 200 g normaalisuolainen", category="10500", contains=("AM",)),
    product("476740", "Juustoportti Kirnuvoi 200 g", category="10500", contains=("AM",)),
    product("475594", "PELTOLAN GOURMET KIRNUVOI N.700G", category="10500", minimal=True),
    product("464315", "PCD 500G MAAPÄHKINÄVOI", category="21453", contains=("AP",)),
    product("462841", "Valrhona Kaakaovoi 3kg", category="22601"),
    product("470097", "Vaasan Voi-kristallipulla 40x90g", category="41764", contains=("UW", "AM"), tc=7),
    # salmon (S-04)
    product("461887", "Kalavapriikki lohi kokonainen", category="18701", contains=("AF",)),
    product("461910", "Kalavapriikki Lohifilee annospala n. 120 g, ASC", category="18701", contains=("AF",)),
    product("461876", "Kirjolohifilee tuore n. 1,5 kg", category="18701", contains=("AF",)),
    product("466146", "Kirjolohi kokonainen", category="18701", contains=("AF",), name_en="Salmon steak"),
    product("474129", "Lohi- ja Katkarapuhampurilainen 5 kg", category="41720", contains=("AF", "AC"), tc=7),
    # gluten-free bread (D-04: wheat starch, oats)
    product("460124", "Fria Kuituleipä 500g gluteeniton", category="41760", contains=("UW",), claims=GF, tc=7),
    product("461765", "Moilas Gluten-Free Tumma leipä 600g", category="41760", claims=GF, tc=7),
    product("468758", "Fazer Gluteeniton Kauraleipä 180g", category="10901", contains=("GO",), claims=GF, tc=8),
    product("475072", "Haapalan laktoositon juustoleipä 500g", category="10640", contains=("AM",), claims=(*LF, *GF)),
    product("468005", "Gluteeniton leipä ERP", category="41760", minimal=True),
    # organic
    product("463883", "Kieku Luomu kananmuna M90", category="10590", contains=("AE",)),
    product("463982", "Kieku Vapaan kanan muna L180", category="10590", contains=("AE",)),
    product("472000", "Kieku kananmuna M10", category="10590", contains=("AE",), labels=("EU_ORGANIC_FARMING",)),
    product("466652", "Panda Suklaamuna 20g", category="52290", contains=("AM",), tc=8),
    # placeholder junk
    product("465611", "NÄYTE", category="10400"),
]


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    d = tmp_path_factory.mktemp("search")
    src = d / "products.json"
    src.write_text(json.dumps(PRODUCTS, ensure_ascii=False), encoding="utf-8")
    db = d / "catalog.db"
    build(src, db)
    c = open_catalog(db)
    yield c
    c.close()


def tiny(tmp_path: Path, products: list[dict]) -> sqlite3.Connection:
    src = tmp_path / "products.json"
    src.write_text(json.dumps(products, ensure_ascii=False), encoding="utf-8")
    build(src, tmp_path / "catalog.db")
    return open_catalog(tmp_path / "catalog.db")


# ---- 4.1-4.2 heads on compound ends, exclusions applied by the tool -----------------------------


def test_lactose_free_milk_is_milk_not_chocolate_or_ice_cream(conn):
    r = search(conn, "laktoositon maito", heads=["maito", "maitojuoma"], must_claims=["FREE_FROM_LACTOSE"])
    assert set(r.ids) == {"464306", "464201", "464119"}  # S-02
    for bad in ("466215", "461000", "462000"):  # maitosuklaa, maitojäätelö, the hyphenated Maito-suklaajuoma
        assert bad not in r.ids
    assert "464237" not in r.ids  # kahvimaito: coffee milk is a default compound modifier of 'maito' (S-03)
    assert r.interpretation["dropped"]["low_lactose_only"] == 1  # X-24: 463047 vähälaktoosinen
    assert r.mode == "heads" and r.interpretation["fts_match"].startswith("rev_fi")


def test_naming_the_variant_as_head_finds_it(conn):
    assert search(conn, "kahvimaito", heads=["kahvimaito"]).ids == ["464237"]


def test_lohi_is_not_kirjolohi(conn):
    r = search(conn, "lohi", heads=["lohi", "lohifilee"])
    assert set(r.ids) == {"461887", "461910"}
    assert r.interpretation["dropped"]["compound_modifier"] == 2  # kirjolohi, kirjolohifilee
    assert "474129" not in r.ids  # 'Lohi- ja katkarapuhampurilainen' is a burger
    assert search(conn, "kirjolohi", heads=["kirjolohi"]).ids  # asked by name, it is found


def test_voi_is_not_peanut_butter_cocoa_butter_or_a_bun(conn):
    r = search(conn, "voi", heads=["voi"])
    assert set(r.ids) == {"463798", "476740", "475594"}
    assert r.interpretation["dropped"] == {"compound_modifier": 2, "hyphen_modifier": 1}
    assert r.ids.index("476740") < r.ids.index("475594")  # the ERP-only kirnuvoi ranks after the full record
    erp = r.hits[r.ids.index("475594")]
    assert "allergen data unknown" in erp.warnings and "minimal ERP record: no GS1 data" in erp.warnings


def test_caller_exclusions_are_applied(conn):
    r = search(conn, "voi", heads=["voi"], exclude=["kirnu"])
    assert r.ids == ["463798"]
    assert r.interpretation["dropped"]["excluded_term"] == 2
    # a short exclusion matches whole words only: 'voi' does not exclude 'kirnuvoi'
    assert set(search(conn, "", heads=["kirnuvoi"], exclude=["voi"]).ids) == {"476740", "475594"}


def test_match_head_reports_why_a_word_is_ruled_out():
    heads = parse_heads(["voi"])
    assert match_head("PCD 500G MAAPÄHKINÄVOI", heads) == "compound_modifier"
    assert match_head("Vaasan Voi-kristallipulla", heads) == "hyphen_modifier"
    m = match_head("Arla Pro meijerivoi 500 g", heads)
    assert m is not None and not isinstance(m, str) and (m.word, m.modifier) == ("meijerivoi", "meijeri")
    assert match_head("Valio kerma", heads) is None


# ---- 4.3 diet semantics (S-05) ------------------------------------------------------------------


def test_lactose_free_keeps_milk_protein_and_says_so(conn):
    r = search(conn, "", heads=["maitojuoma"], must_claims=["FREE_FROM_LACTOSE"])
    assert r.ids == ["464306"]
    assert any("milk protein (AM)" in w for w in r.hits[0].warnings)


def test_milk_free_excludes_lactose_free_milk(conn):
    r = search(conn, "maidoton juoma", heads=["juoma"])
    assert r.interpretation["banned_allergens"] == ["AM"]
    assert set(r.ids) == {"468000", "468465", "468466"}  # the plant drinks; every milk drink declares AM
    assert "allergen words in the query applied: AM" in r.warnings


def test_gluten_free_excludes_wheat_starch_and_oats_unless_allowed(conn):
    r = search(conn, "gluteeniton leipä", heads=["leipä"], must_claims=["FREE_FROM_GLUTEN"])
    assert r.ids == ["461765"]
    assert r.interpretation["banned_allergens"] == ["AW", "GB", "GO", "NR", "UW"]
    d = r.interpretation["dropped"]
    assert d["allergen_contains"] == 2  # 460124 wheat starch (UW), 468758 oats (GO)
    assert d["compound_modifier"] == 1  # juustoleipä is a cheese
    assert d["claim_unknown"] == 1  # the ERP-only record has no claim data, so it cannot be gluten-free

    allowed = search(conn, "gluteeniton leipä", heads=["leipä"], must_claims=["FREE_FROM_GLUTEN"], allow_oats=True)
    assert set(allowed.ids) == {"461765", "468758"}
    assert "460124" not in allowed.ids
    assert any("oats (GO)" in w for h in allowed.hits for w in h.warnings)


def test_gluten_free_oat_drinks_x27(conn):
    kw = {"heads": ["kaurajuoma"], "must_claims": ["FREE_FROM_GLUTEN"]}
    assert search(conn, "gluteeniton kaurajuoma", **kw).ids == []  # oats excluded by default
    # oats allowed: the gluten-free claim with oats only passes; 468000 has no claim and declares AW
    assert search(conn, "gluteeniton kaurajuoma", **kw, allow_oats=True).ids == ["468465"]


def test_unknown_allergen_data_is_never_safe(conn):
    r = search(conn, "voi", heads=["voi"], must_not_allergens=["AP"])
    assert "475594" not in r.ids  # the ERP-only kirnuvoi has no allergen data
    assert r.interpretation["dropped"]["allergens_unknown"] == 1
    assert set(r.ids) == {"463798", "476740"}


def test_may_contain_warns_or_drops_when_strict(tmp_path):
    c = tiny(tmp_path, [product("469999", "Testivoi 200 g", category="10500", may_contain=("AN",))])
    try:
        r = search(c, "", heads=["voi"], must_not_allergens=["AN"])
        assert r.ids == ["469999"] and "may contain AN" in r.hits[0].warnings
        assert search(c, "", heads=["voi"], must_not_allergens=["AN"], strict_may_contain=True).ids == []
    finally:
        c.close()


def test_claim_and_allergen_names_are_normalised(conn):
    r = search(conn, "", heads=["maito"], must_claims=["lactose-free"], must_not_allergens=["peanut", "bogus!!"])
    assert r.interpretation["must_claims"] == ["FREE_FROM_LACTOSE"]
    assert r.interpretation["banned_allergens"] == ["AP"]
    assert any("not GS1 allergen codes" in w for w in r.warnings)


def test_unknown_claim_code_matches_nothing(conn):
    assert search(conn, "", heads=["maito"], must_claims=["NOT_A_CLAIM"]).ids == []


def test_temperature_filter_keeps_unknown_with_a_warning(conn, tmp_path):
    r = search(conn, "lohi", heads=["lohi", "lohifilee"], temperature="frozen")
    assert r.ids == [] and r.interpretation["dropped"]["temperature"] == 2  # both salmon are chilled
    assert len(search(conn, "lohi", heads=["lohi", "lohifilee"], temperature="chilled").ids) == 2
    c = tiny(tmp_path, [product("469998", "Testivoi 1 kg", category="10500", contains=("AM",), tc=None)])
    try:
        r = search(c, "", heads=["voi"], temperature="frozen")
        assert r.ids == ["469998"] and "temperature class unknown" in r.hits[0].warnings
    finally:
        c.close()


def test_organic_from_label_or_name(conn):
    r = search(conn, "organic eggs", heads=["kananmuna", "muna"])
    assert r.interpretation["organic"] is True
    assert set(r.ids) == {"463883", "472000"}  # 'Luomu' in the name, EU organic label
    assert "466652" not in search(conn, "", heads=["muna"]).ids  # suklaamuna is a default modifier


def test_placeholder_is_dropped(conn):
    assert "465611" not in search(conn, "näyte", heads=["näyte"]).ids


# ---- query without heads, ranking ---------------------------------------------------------------


def test_free_text_query_derives_claims_and_heads(conn):
    r = search(conn, "lactose free milk")
    assert r.interpretation["heads_from_query"] is True
    assert r.interpretation["heads"] == ["maito", "maitojuoma"]
    assert r.interpretation["implied_claims"] == ["FREE_FROM_LACTOSE"]
    assert set(r.ids) == {"464306", "464201", "464119"}
    assert set(search(conn, "butter").ids) == {"463798", "476740", "475594"}


def test_free_text_falls_back_to_prefix_match(conn):
    r = search(conn, "semi skimmed")  # no fi word ends in 'skimmed'; the en name has both words
    assert r.mode == "text" and r.ids == ["464306"]


def test_query_words_rank_first(conn):
    r = search(conn, "kirnuvoi", heads=["voi"])
    assert r.ids[0] in {"476740", "475594"} and r.ids[-1] == "463798"


def test_summaries_fit_the_contract(conn):
    r = search(conn, "laktoositon maito", heads=["maito", "maitojuoma"], must_claims=["FREE_FROM_LACTOSE"])
    for h in r.hits:
        ProductSummary(**h.summary())
    d = r.as_dict()
    assert d["total_matches"] == 3 and d["products"][0]["why"]
    assert json.dumps(d)  # serialisable for the route


def test_limit_is_clamped(conn):
    assert len(search(conn, "", heads=["maito", "maitojuoma", "voi"], limit=1).ids) == 1
    assert search(conn, "", heads=["voi"], limit=0).ids  # clamped to 1, not an error
    assert search(conn, "", heads=["voi"], limit="x").ids  # type: ignore[arg-type]


# ---- 4.4 robust input ---------------------------------------------------------------------------


def test_match_terms_are_quoted():
    assert quote('a"b') == '"a""b"'
    assert head_match_expr(parse_heads(["Maito", "maito-juoma"])) == 'rev_fi : ("otiam"* OR "amouj"*)'
    assert head_match_expr(parse_heads(['x" OR rev_fi:*'])) == 'rev_fi : ("if"*)'  # only word tokens survive


FUZZ = [
    "",
    " ",
    '"',
    '""',
    "'",
    'maito"',
    "kevyt-maito",
    "-maito",
    "maito-",
    "100%",
    "%",
    "50 % rasvaa",
    "(maito",
    "maito)",
    "((()))",
    "maito AND",
    "AND",
    "OR OR",
    "NOT maito",
    "NEAR(maito voi)",
    "maito*",
    "*",
    "^maito",
    "rev_fi:otiam",
    "name_fi : maito",
    "{name_fi}: x",
    "maito; DROP TABLE products;--",
    "\x00maito",
    "maito\nvoi\ttab",
    "😀 maito",
    "a" * 5000,
    "ä",
    "ö-å",
    "Maito & Voi",
    "1,5 l",
]


@pytest.mark.parametrize("text", FUZZ)
def test_fuzzed_input_never_raises(conn, text):
    for kwargs in (
        {"query": text},
        {"query": text, "heads": [text]},
        {"query": "maito", "heads": ["maito"], "exclude": [text]},
        {"query": text, "must_claims": [text], "must_not_allergens": [text], "temperature": text},
    ):
        r = search(conn, **kwargs)
        assert isinstance(r.ids, list) and r.total_matches >= len(r.ids)


def test_non_string_input_never_raises(conn):
    r = search(conn, None, heads=[None, 5, "voi"], exclude=[None], must_claims=[3])  # type: ignore[arg-type,list-item]
    assert r.ids


def test_fts_error_falls_back_to_trigram_and_rapidfuzz(conn, monkeypatch):
    def broken(*_a, **_k):
        raise sqlite3.OperationalError("fts5: syntax error")

    monkeypatch.setattr(search_mod, "_fts_rows", broken)
    r = search(conn, "kevytmaitojuoma", heads=["kevytmaitojuoma"], must_claims=["FREE_FROM_LACTOSE"])
    assert r.mode == "fuzzy"
    assert r.ids[0] == "464306"
    assert any("index query failed" in w for w in r.warnings)
    assert all(h.fuzzy_score is not None and h.fuzzy_score >= 75 for h in r.hits)


def test_misspelt_head_finds_close_spellings(conn):
    r = search(conn, "kevytmaitojuma", heads=["kevytmaitojuma"])  # no word ends in the typo
    assert r.mode == "fuzzy" and r.ids[0] == "464306"
    assert "no exact name match; showing close spellings" in r.warnings


def test_fuzzy_results_still_pass_the_diet_filters(conn, monkeypatch):
    def broken(*_a, **_k):
        raise sqlite3.OperationalError("fts5: syntax error")

    monkeypatch.setattr(search_mod, "_fts_rows", broken)
    r = search(conn, "maito", heads=["maito"], must_claims=["FREE_FROM_LACTOSE"], must_not_allergens=["AM"])
    assert r.ids == []  # every lactose-free milk declares AM


# ---- 4.5 golden set -----------------------------------------------------------------------------


def test_golden_set_is_well_formed():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    qs = golden["queries"]
    scored = [q for q in qs if q.get("scored", True)]
    assert len(scored) >= 20
    assert {q["lang"] for q in scored} == {"fi", "en"}
    assert len({q["id"] for q in qs}) == len(qs)
    for q in qs:
        assert all(len(i) == 6 and i.isdigit() for i in q["relevant"] + q["never"]), q["id"]
        assert not set(q["relevant"]) & set(q["never"]), q["id"]
        assert set(q["args"]) <= {
            "query",
            "heads",
            "exclude",
            "must_claims",
            "must_not_allergens",
            "temperature",
            "allow_oats",
        }, q["id"]
        if q.get("scored", True):
            assert q["relevant"], q["id"]


def test_evaluate_scores_a_tiny_golden_set(conn):
    golden = {
        "k": 10,
        "queries": [
            {
                "id": "milk",
                "lang": "fi",
                "relevant": ["464306", "464201"],
                "never": ["466215"],
                "args": {
                    "query": "laktoositon maito",
                    "heads": ["maito", "maitojuoma"],
                    "must_claims": ["FREE_FROM_LACTOSE"],
                },
            },
            {
                "id": "x27",
                "lang": "fi",
                "relevant": [],
                "never": ["468000"],
                "scored": False,
                "args": {
                    "query": "gluteeniton kaurajuoma",
                    "heads": ["kaurajuoma"],
                    "must_claims": ["FREE_FROM_GLUTEN"],
                },
            },
        ],
    }
    report = evaluate(conn, golden)
    assert report["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert report["queries"][0]["misses"] == ["464119"]
    assert report["never_violations"] == 0


REAL_DB = REPO / "data" / "catalog.db"


@pytest.mark.skipif(not REAL_DB.exists(), reason="needs the real catalogue (scripts/build_catalog.py); CI has none")
def test_golden_precision_on_the_real_catalogue():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    c = open_catalog(REAL_DB)
    try:
        report = evaluate(c, golden)
    finally:
        c.close()
    assert report["never_violations"] == 0, [q for q in report["queries"] if q["never_seen"]]
    assert report["precision"] >= golden["target_precision"]


def test_diet_words_alone_are_not_a_product(conn):
    r = search(conn, "laktoositon")
    assert r.ids == [] and r.interpretation["must_claims"] == ["FREE_FROM_LACTOSE"]
    assert "no product type in the request: send heads or product words" in r.warnings
