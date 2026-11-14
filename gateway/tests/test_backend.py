"""The backend switch (app/backend.py): the real catalogue with recorded Valio Aimo answers, through the HTTP routes.

A tiny catalog.db is built with the M2 builder from the hand-made W-03-shaped records of test_offers, and a tiny
recording in the M3 replay layout (scripts/record_fixtures.py) holds their /availability and /price answers. The app
runs on CatalogBackend in replay mode, so no network and no real data. One test at the end runs W-03 on the real
data in data/ and is skipped when that data is absent (CI).
"""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from app.backend import CatalogBackend, StubBackend, resolve_mode
from app.catalog import build
from app.fmt import instant
from app.main import create_app
from app.settings import REPO_ROOT, Settings
from app.stubs import vat_of
from conftest import FakeLLM, FakeVoice
from fastapi.testclient import TestClient
from test_offers import AVAIL, CARBON, DRINKS, HEADLINE, MILKS, PRICES, RELIABILITY, SAT_10

DAY = "2026-11-16"
TIME_NOW = "2026-11-14T20:20:16+0200"
RECORDED = "2026-11-14T18:20:15+00:00"
VAT_25 = "463335"  # its recorded taxRate is 25.5, so a quote's VAT can only have come from the API answer
REAL_DB = REPO_ROOT / "data" / "catalog.db"
REAL_FIXTURES = REPO_ROOT / "data" / "fixtures"


def write_recording(root: Path, avail: dict, prices: dict, day: str = DAY) -> list[dict]:
    """One availability and one price body for `day`, with a manifest, as scripts/record_fixtures.py writes them."""
    files = []
    for endpoint, body in (
        ("availability", {"timeNow": TIME_NOW, "products": list(avail.values())}),
        ("price", {"products": list(prices.values())}),
    ):
        rel = Path("raw") / "named" / day / f"{endpoint}-000.json"
        raw = json.dumps(body).encode()
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(raw)
        files.append(
            {
                "set": "named",
                "endpoint": endpoint,
                "requested_date": day,
                "path": str(rel),
                "http_status": 200,
                "ids": [p["productId"] for p in body["products"]],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "time_now": body.get("timeNow"),
                "request": {"customer": "123", "requestedDate": day},
            }
        )
    manifest = {"recorded_started_at": RECORDED, "customer": "123", "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return files


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("backend")
    products = MILKS + DRINKS
    (d / "products.json").write_text(json.dumps(products, ensure_ascii=False), encoding="utf-8")
    rel = "productId,deliveryReliability\n" + "".join(f"{k},{v}\n" for k, v in RELIABILITY.items())
    carb = "productId,AVG kg CO2-eq/kg\n" + "".join(f"{p['id']},{CARBON.get(p['id'], 1.1)}\n" for p in products)
    (d / "rel.csv").write_text(rel, encoding="utf-8")
    (d / "carbon.csv").write_text(carb, encoding="utf-8")
    build(d / "products.json", d / "catalog.db", d / "rel.csv", d / "carbon.csv")
    prices = {k: json.loads(json.dumps(v)) for k, v in PRICES.items()}
    prices[VAT_25]["tax"]["taxRate"] = 25.5
    files = write_recording(d / "fixtures", AVAIL, prices)
    return {"catalog_db": d / "catalog.db", "fixtures_dir": d / "fixtures", "files": files, "n": len(products)}


def catalog_settings(data: dict, tmp_path: Path, **kw) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "gw.db",
        web_dist=None,
        valio_mode="replay",
        catalog_db=data["catalog_db"],
        fixtures_dir=data["fixtures_dir"],
        **kw,
    )


@pytest.fixture
def cat(data, tmp_path):
    """A signed-in chef on an app that runs on the catalogue with the tiny recording."""
    c = TestClient(create_app(catalog_settings(data, tmp_path), voice=FakeVoice(), llm=FakeLLM()))
    assert c.post("/api/login", json={"buyer_id": "chef"}).status_code == 200
    yield c
    c.app.state.backend.close()


# ---- picking the backend -----------------------------------------------------------------------


def test_auto_picks_the_catalogue_only_when_catalog_db_and_the_recording_both_exist(data, tmp_path):
    def mode(**kw) -> str:
        return resolve_mode(Settings(_env_file=None, db_path=tmp_path / "gw.db", **kw))

    both = {"catalog_db": data["catalog_db"], "fixtures_dir": data["fixtures_dir"]}
    assert mode(**both) == "replay"
    assert mode(**{**both, "fixtures_dir": tmp_path / "none"}) == "stub"
    assert mode(**{**both, "catalog_db": tmp_path / "none.db"}) == "stub"
    assert mode(**both, valio_mode="stub") == "stub"
    assert mode(**both, valio_mode="LIVE") == "live"


def test_the_suite_runs_on_the_stub_catalogue(client):
    assert isinstance(client.app.state.backend, StubBackend)
    assert client.app.state.stubs.backend is client.app.state.backend
    assert client.get("/health").json()["mode"] == "stub"


def test_health_reports_the_mode_the_catalogue_and_the_recording(cat, data):
    h = cat.get("/health").json()
    assert isinstance(cat.app.state.backend, CatalogBackend)
    assert (h["status"], h["mode"], h["catalogue"], h["products"]) == ("ok", "replay", "catalog.db", data["n"])
    assert h["fixtures_recorded_at"] == RECORDED and h["catalogue_built_at"]


# ---- reads -------------------------------------------------------------------------------------


def test_search_get_product_and_plan_quantity_read_the_catalogue(cat):
    found = cat.post("/v1/products/search", json={"query": "kahvimaito", "heads": ["kahvimaito"]}).json()
    assert {p["product_id"] for p in found["products"]} == {"464237", "462626"}  # the two coffee milks
    p = cat.get("/v1/products/464306").json()
    assert p["product"]["claims"] == ["FREE_FROM_LACTOSE"] and p["json_ld"]["sku"] == "464306"
    assert cat.get("/v1/products/470999").status_code == 404
    plan = cat.post("/v1/quantity/plan", json={"product_id": "464306", "amount": 1000, "unit": "L"}).json()
    assert (plan["api_unit"], plan["units_needed"], plan["total_content"]) == ("ST", 1000, "1000")


# ---- offers, quote, basket, order ----------------------------------------------------------------


def test_get_offers_runs_m5_on_the_recording_and_registers_the_offer_set(cat):
    res = cat.post("/v1/offers", json=HEADLINE).json()
    best = res["options"][0]
    assert (best["product_id"], best["qty"], best["total_net"], best["tier"]) == ("464306", 1000, "1010.00", "best")
    assert res["counts"]["cutoff_passed_terminal"] >= 1 and "CUTOFF_PASSED" in {
        f for n in res["not_offered"] for f in n["flags"]
    }
    assert not any("stub" in w for w in res["warnings"])
    assert cat.get(f"/v1/offers/{res['offer_set_id']}").json()["options"][0]["offer_id"] == best["offer_id"]


def test_a_quote_takes_vat_expiry_and_evidence_from_the_backend(cat, data):
    res = cat.post("/v1/offers", json=HEADLINE).json()
    offer = next(o for o in res["options"] if o["product_id"] == VAT_25)
    q = cat.post("/v1/quotes", json={"offer_id": offer["offer_id"]}).json()
    line = q["quote"]["lines"][0]
    vat = vat_of(Decimal(offer["total_net"]), Decimal("25.5"))
    assert (line["vat_rate"], line["line_net"], line["line_vat"]) == ("25.5", offer["total_net"], str(vat))
    assert q["total_gross"] == str(Decimal(offer["total_net"]) + vat)
    assert q["expires_at"] == "2026-11-14T10:15:00+02:00"  # issue + 15 min, before the Sunday cut-off
    ev = q["quote"]["evidence"]
    assert ev["stub"] is False and ev["api_time_now"] == TIME_NOW
    assert set(ev["response_sha256"]) == {f["sha256"] for f in data["files"]}
    assert q["warnings"] == []


def test_add_to_basket_a_sheet_row_by_product_id_quote_confirm_and_order(cat):
    need = {**HEADLINE, "amount": 100, "basket_id": "new"}
    b = cat.post("/v1/baskets/lines", json=need).json()
    first = b["line"]
    assert (first["status"], first["product_id"], first["offer"]["total_net"]) == ("priced", "464306", "101.00")
    basket_id = b["basket_id"]

    sheet = "tuotenumero;tuote;määrä;yksikkö;toimituspäivä\n464401;;50;l;16.11.2026\n"
    files = {"file": ("lista.csv", sheet.encode(), "text/csv")}
    imp = cat.post("/v1/baskets/import", files=files, data={"basket_id": basket_id}).json()
    row = imp["rows"][0]
    assert row["status"] == "priced", row
    line = next(x for x in imp["basket"]["lines"] if x["line_id"] == row["line_id"])
    assert (line["product_id"], line["offer"]["qty"], line["offer"]["total_net"]) == ("464401", 50, "55.00")
    assert line["vat_rate"] == "13.5" and line["line_vat"] == "7.43"

    q = cat.post("/v1/baskets/quote", json={"basket_id": basket_id}).json()
    assert (q["status"], q["total_net"]) == ("ready_for_complete", "156.00")
    assert [x["product_id"] for x in q["quote"]["lines"]] == ["464306", "464401"]
    assert q["quote"]["evidence"]["stub"] is False
    assert cat.post(f"/v1/quotes/{q['quote_id']}/confirm").json()["confirmed"] is True
    o = cat.post("/v1/orders", json={"quote_id": q["quote_id"]}).json()
    assert (o["status"], o["reason_code"], o["total_net"]) == ("completed", None, "156.00"), o
    assert o["order"]["receipt_jws"]


def test_the_pre_order_recheck_reads_the_recording_again(cat):
    res = cat.post("/v1/offers", json={**HEADLINE, "amount": 100}).json()
    q = cat.post("/v1/quotes", json={"offer_id": res["options"][0]["offer_id"]}).json()
    backend = cat.app.state.backend
    line = q["quote"]["lines"][0]
    cur = backend.current(line["product_id"], line["qty"], line["delivery_date"], instant(SAT_10))
    assert cur is not None and cur.unit_price == Decimal("1.01") and cur.blocking == ()
    assert backend.current("470999", 1, DAY, instant(SAT_10)) is None  # not in the catalogue


# ---- the real data (skipped in CI) ---------------------------------------------------------------


@pytest.mark.skipif(
    not (REAL_DB.is_file() and (REAL_FIXTURES / "manifest.json").is_file()),
    reason="needs the real data: data/catalog.db (scripts/build_catalog.py) and data/fixtures (record_fixtures.py)",
)
def test_w03_on_the_real_catalogue_and_recording(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "gw.db", web_dist=None, valio_mode="replay")
    c = TestClient(create_app(s, voice=FakeVoice(), llm=FakeLLM()))
    try:
        assert c.post("/api/login", json={"buyer_id": "chef"}).status_code == 200
        res = c.post("/v1/offers", json=HEADLINE).json()
        best = res["options"][0]
        assert (best["product_id"], best["qty"], best["api_unit"]) == ("464306", 1000, "ST")
        assert (best["total_net"], best["tier"]) == ("1010.00", "best") and "NET_PRICE" in best["flags"]
        assert res["counts"]["stock_full"] == 8 and res["counts"]["terminal_full"] == 0
        assert res["counts"]["cutoff_passed_terminal"] == 16
        assert c.get("/health").json()["products"] == 17546
    finally:
        c.app.state.backend.close()
