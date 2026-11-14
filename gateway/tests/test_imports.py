"""Excel and CSV import (docs/basket-plan.md M25.2, M25.4): rows become basket lines, matched and priced."""

import io
from datetime import date, datetime

import pytest
from app.basket import MAX_LINES, service
from app.identity import BUYERS
from app.imports import next_delivery_date
from app.sheets import MAX_BYTES, MAX_ROWS
from conftest import voice_headers
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

CHEF = BUYERS["chef"]
HEADER = "tuotenumero;tuote;määrä;yksikkö;toimituspäivä;lisätieto\n"
CSV = (
    HEADER
    + "464076;;7,5;kg;16.11.2026;\n"  # 2: the id, a decimal comma: priced
    + ";kuohukerma;4;l;16.11.2026;\n"  # 3: two creams: needs_choice
    + ";vehnäjauho;;kg;16.11.2026;\n"  # 4: one flour, no amount: needs_amount
    + ";servetit;500;kpl;16.11.2026;\n"  # 5: not in the catalogue: unmatched
    + ";;3;kg;16.11.2026;\n"  # 6: nothing to match: invalid
    + "469119;;10,5;l;;takaovelle\n"  # 7: a Terminal milk without a date: the next deliverable date
)


def upload(c: TestClient, data: bytes | str, name: str = "lista.csv", basket_id: str = "new", ctype: str = "text/csv"):
    body = data.encode() if isinstance(data, str) else data
    return c.post("/v1/baskets/import", files={"file": (name, body, ctype)}, data={"basket_id": basket_id})


def imported(c: TestClient, data: bytes | str, **kw) -> dict:
    r = upload(c, data, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def by_row(res: dict) -> dict[int, dict]:
    return {r["row_number"]: r for r in res["rows"]}


def line(res: dict, line_id: int) -> dict:
    return next(x for x in res["basket"]["lines"] if x["line_id"] == line_id)


@pytest.fixture
def svc(client, settings):
    return service(client.app, settings)


def test_a_csv_with_semicolons_and_a_decimal_comma(chef):
    res = imported(chef, CSV)
    rows = by_row(res)
    assert {n: r["status"] for n, r in rows.items()} == {
        2: "priced",
        3: "needs_choice",
        4: "needs_amount",
        5: "unmatched",
        6: "invalid",
        7: "priced",
    }
    butter = line(res, rows[2]["line_id"])
    assert (butter["product_id"], butter["amount"], butter["unit"], butter["source"]) == ("464076", 7.5, "KG", "import")
    assert butter["offer"]["qty"] == 2 and butter["need_date"] == "2026-11-16"
    cream = line(res, rows[3]["line_id"])
    assert cream["product_id"] is None and {o["product_id"] for o in cream["alternatives"]} == {"467318", "469346"}
    assert line(res, rows[4]["line_id"])["amount"] is None
    napkins = line(res, rows[5]["line_id"])
    assert napkins["need_text"] == "servetit" and "servetit" in napkins["raw_text"] and napkins["amount"] == 500
    assert rows[6]["line_id"] is None and "no product id" in rows[6]["message"]["en"]
    assert all(r["message"]["fi"] and r["message"]["en"] for r in res["rows"])


def test_rows_that_need_attention_come_first_and_are_counted(chef):
    res = imported(chef, CSV)
    assert [r["row_number"] for r in res["rows"]] == [3, 4, 5, 6, 2, 7]
    assert res["counts"] == {
        "priced": 2,
        "needs_choice": 1,
        "needs_amount": 1,
        "unmatched": 1,
        "not_deliverable": 0,
        "cutoff_passed": 0,
        "invalid": 1,
    }
    assert res["message_for_user"]["en"].startswith(
        "6 rows: 2 priced, 1 needs your choice, 1 needs an amount, 1 not found, 1 invalid."
    )
    assert "Row 7 had no delivery date" in res["message_for_user"]["en"]
    assert res["basket"]["counts"]["priced"] == 2 and len(res["basket"]["lines"]) == 5
    assert res["extraction"] is None and res["status"] == "ok"


def test_a_missing_date_becomes_the_next_deliverable_date(chef):
    milk = by_row(imported(chef, CSV))[7]
    # 469119 comes from a supplier's warehouse: order by 15:00 four days before, so Wed 18.11 is the first date.
    assert milk["status"] == "priced" and "next delivery date, Wed 18.11" in milk["message"]["en"]
    assert "seuraavaa toimituspäivää ke 18.11." in milk["message"]["fi"]


def test_next_delivery_date(client, svc):
    as_of = "2026-11-14T10:00:00+02:00"
    assert next_delivery_date(svc.stubs, as_of, None) == date(2026, 11, 15)  # no product: the next day
    assert next_delivery_date(svc.stubs, as_of, "464076") == date(2026, 11, 15)  # stock: by 17:00 the day before
    assert next_delivery_date(svc.stubs, as_of, "469119") == date(2026, 11, 18)  # Terminal: four days
    assert next_delivery_date(svc.stubs, as_of, "464440") == date(2026, 11, 15)  # never deliverable: the next day
    assert next_delivery_date(svc.stubs, "2026-11-14T18:00:00+02:00", "464076") == date(2026, 11, 16)
    weekdays = {0, 1, 2, 3, 4}  # Chef Aada's mandate: Monday to Friday
    assert next_delivery_date(svc.stubs, as_of, None, weekdays) == date(2026, 11, 16)  # Sunday 15.11 skipped
    assert next_delivery_date(svc.stubs, as_of, "464076", weekdays) == date(2026, 11, 16)
    assert next_delivery_date(svc.stubs, as_of, "469119", weekdays) == date(2026, 11, 18)


def test_an_xlsx_built_in_the_test(chef):
    book = Workbook()
    sheet = book.active
    sheet.append(["Product id", "Name", "Quantity", "Unit", "Delivery date", "Note"])
    sheet.append(["472535", "", 120, "PCS", datetime(2026, 11, 17), None])
    sheet.append([None, "laktoositon maitorahka", 5, "kg", datetime(2026, 11, 17), "takaovelle"])
    sheet.append([None, "kerma", None, None, None, None])
    sheet.append([None, "sardiinit", 10, "kg", datetime(2026, 11, 17), None])
    out = io.BytesIO()
    book.save(out)
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    res = imported(chef, out.getvalue(), name="tilaus.xlsx", ctype=xlsx)
    rows = by_row(res)
    assert {n: r["status"] for n, r in rows.items()} == {2: "priced", 3: "priced", 4: "needs_amount", 5: "unmatched"}
    eggs = line(res, rows[2]["line_id"])
    assert (eggs["product_id"], eggs["need_date"], eggs["offer"]["qty"]) == ("472535", "2026-11-17", 2)
    assert line(res, rows[3]["line_id"])["product_id"] == "465731"
    cream = line(res, rows[4]["line_id"])  # four creams, but no amount yet: the amount comes first
    # No date: the next day Chef Aada's mandate allows (Mon-Fri), so not Sunday 15.11, which would need an approval.
    assert cream["amount"] is None and cream["need_date"] == "2026-11-16"


def test_a_single_close_name_waits_for_the_buyer(chef):
    """'rahka' is close to one product only: a wrong product priced silently is the worst outcome, so it asks."""
    res = imported(chef, HEADER + ";rahka;2;kg;16.11.2026;\n")
    row = res["rows"][0]
    assert row["status"] == "needs_choice" and "Check the suggested product" in row["message"]["en"]
    rahka = line(res, row["line_id"])
    assert rahka["product_id"] is None and [o["product_id"] for o in rahka["alternatives"]] == ["465731"]
    choice = rahka["alternatives"][0]["offer_id"]
    r = chef.patch(f"/v1/baskets/{res['basket_id']}/lines/{row['line_id']}", json={"offer_id": choice})
    assert r.status_code == 200 and r.json()["line"]["status"] == "priced"


def test_an_exact_id_line_has_alternatives_to_swap_to(chef):
    res = imported(chef, HEADER + "464076;;7,5;kg;16.11.2026;\n")
    row = res["rows"][0]
    butter = line(res, row["line_id"])
    assert (row["status"], butter["product_id"]) == ("priced", "464076")
    assert butter["alternatives"] and "464076" not in {o["product_id"] for o in butter["alternatives"]}
    alt = butter["alternatives"][0]
    r = chef.patch(f"/v1/baskets/{res['basket_id']}/lines/{row['line_id']}", json={"offer_id": alt["offer_id"]})
    swapped = r.json()["line"]
    assert r.status_code == 200 and (swapped["status"], swapped["product_id"]) == ("priced", alt["product_id"])
    assert "464076" in {o["product_id"] for o in swapped["alternatives"]}  # and back again


def test_a_row_already_in_the_basket_reports_that_line(chef):
    first = imported(chef, CSV)
    again = imported(
        chef,
        HEADER + "464076;;7,5;kg;16.11.2026;\n;servetit;500;kpl;16.11.2026;\n;pillit;500;kpl;16.11.2026;\n",
        basket_id=first["basket_id"],
    )
    rows = by_row(again)
    assert rows[2]["line_id"] == by_row(first)[2]["line_id"] and "already line" in rows[2]["message"]["en"]
    assert rows[3]["line_id"] == by_row(first)[5]["line_id"]
    assert rows[4]["line_id"] not in {x["line_id"] for x in first["basket"]["lines"]}  # other words: a new line
    assert len(again["basket"]["lines"]) == len(first["basket"]["lines"]) + 1
    assert "Rows 2 and 3 were already in the basket" in again["message_for_user"]["en"]


def test_two_identical_rows_in_one_file_make_one_line(chef):
    res = imported(chef, HEADER + ";vehnäjauho;2;kg;16.11.2026;\n;vehnäjauho;2;kg;16.11.2026;\n")
    rows = by_row(res)
    assert rows[2]["line_id"] == rows[3]["line_id"] and len(res["basket"]["lines"]) == 1
    assert "already line" not in rows[2]["message"]["en"] and "already line" in rows[3]["message"]["en"]


def test_an_import_adds_to_the_basket_in_focus(chef):
    first = imported(chef, CSV)
    second = imported(chef, HEADER + ";kananmuna;90;kpl;16.11.2026;\n", basket_id=first["basket_id"])
    assert second["basket_id"] == first["basket_id"] and len(second["basket"]["lines"]) == 6


def test_files_that_cannot_be_read(chef):
    r = upload(chef, HEADER + ";maito;1;l;;\n" + "x" * (MAX_BYTES + 10))
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    r = upload(
        chef, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, name="vanha.xls", ctype="application/vnd.ms-excel"
    )
    assert r.status_code == 415 and ".xls" in r.json()["detail"]
    r = upload(chef, b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, name="kuva.png", ctype="image/png")
    assert r.status_code == 415
    r = upload(chef, b"", name="tyhja.csv")
    assert r.status_code == 422 and r.json()["detail"] == "The file is empty."
    many = HEADER + "".join(f";tuote {i};1;kg;16.11.2026;\n" for i in range(MAX_ROWS + 1))
    r = upload(chef, many)
    assert r.status_code == 422 and str(MAX_ROWS) in r.json()["detail"]
    assert chef.get("/v1/baskets/current").status_code == 404  # nothing was started


def test_a_basket_over_its_line_limit(chef):
    full = HEADER + "".join(f";tuote{i:03d};1;kg;16.11.2026;\n" for i in range(MAX_LINES))
    basket_id = imported(chef, full)["basket_id"]
    r = upload(chef, HEADER + ";vielä yksi;1;kg;16.11.2026;\n", basket_id=basket_id)
    assert r.status_code == 422 and str(MAX_LINES) in r.json()["detail"]
    assert len(chef.get(f"/v1/baskets/{basket_id}").json()["basket"]["lines"]) == MAX_LINES


def test_the_buyer_cookie_only(client, chef):
    session = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    voice = TestClient(client.app)  # the agent's side: voice headers, no cookie
    r = voice.post(
        "/v1/baskets/import",
        files={"file": ("lista.csv", CSV.encode(), "text/csv")},
        data={"basket_id": "new"},
        headers=voice_headers(session),
    )
    assert r.status_code == 401
    assert upload(TestClient(client.app), CSV).status_code == 401


def test_another_buyers_basket_is_not_found(client, chef):
    basket_id = imported(chef, CSV)["basket_id"]
    other = TestClient(client.app)
    assert other.post("/api/login", json={"buyer_id": "head_chef"}).status_code == 200
    assert upload(other, CSV, basket_id=basket_id).status_code == 404
    assert upload(chef, CSV, basket_id="B-0000000000").status_code == 404
    assert upload(chef, CSV, basket_id="nonsense").status_code == 422


def test_an_ordered_basket_is_locked(chef, svc):
    first = imported(chef, CSV)
    svc.mark_ordered(CHEF, first["basket_id"])
    res = imported(chef, CSV, basket_id=first["basket_id"])
    assert res["reason_code"] == "basket_locked" and res["rows"] == []
    assert len(res["basket"]["lines"]) == len(first["basket"]["lines"]) and res["basket"]["status"] == "ordered"
    assert "already ordered" in res["message_for_user"]["en"]


def test_the_template_download_imports_cleanly(client, chef):
    r = client.get("/v1/baskets/template.xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.headers["content-disposition"] == 'attachment; filename="tilauslista-pohja.xlsx"'
    assert load_workbook(io.BytesIO(r.content)).active["A1"].value == "tuotenumero"
    res = imported(chef, r.content, name="tilauslista-pohja.xlsx", ctype=r.headers["content-type"])
    assert len(res["rows"]) == 4 and res["counts"]["invalid"] == 0
    assert by_row(res)[2]["status"] == "priced"  # the milk by its id


def test_routes_are_tagged_ui_and_not_agent_tools(settings):
    from app.main import create_app

    paths = create_app(settings).openapi()["paths"]
    assert paths["/v1/baskets/import"]["post"]["tags"] == ["ui"]
    assert paths["/v1/baskets/template.xlsx"]["get"]["tags"] == ["ui"]
    assert paths["/v1/baskets/import-image"]["post"]["tags"] == ["ui"]
