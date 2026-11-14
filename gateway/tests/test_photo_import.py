"""Photo to basket (docs/basket-plan.md M28): Claude reads the list (FakeLLM here), the import pipeline adds it."""

import struct
import zlib

import pytest
from app.basket import service
from app.contract import ListExtraction
from app.identity import BUYERS
from app.images import MAX_IMAGE_BYTES
from app.llm import LLMRefused, LLMUnavailable
from conftest import voice_headers
from fastapi.testclient import TestClient

# The brief's check list (B-11): "maito 20 l, laktoositon kevytmaito 12 kpl, voi 5 kg, servetit 500 kpl".
LIST = ListExtraction.model_validate(
    {
        "handwritten": True,
        "unreadable": ["a smudge under the last line"],
        "need_date": None,
        "items": [
            {"raw_text": "maito 20 l", "name": "maito", "quantity": 20, "unit": "L", "note": "", "confidence": "high"},
            {
                "raw_text": "laktoositon kevytmaito 12 kpl",
                "name": "laktoositon kevytmaito",
                "quantity": 12,
                "unit": "PCS",
                "note": "",
                "confidence": "medium",
            },
            {"raw_text": "voi 5 kg", "name": "voi", "quantity": 5, "unit": "KG", "note": "", "confidence": "high"},
            {
                "raw_text": "servetit 500 kpl",
                "name": "servetit",
                "quantity": 500,
                "unit": "PCS",
                "note": "valkoiset",
                "confidence": "low",
            },
        ],
    }
)
MILKS = {"464306", "464401", "464237", "463335", "464201", "464073", "464398", "469363", "465244", "464440"}


def png(width: int = 40, height: int = 20) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00" * (width * 3 + 1) * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def send(c: TestClient, data: bytes, basket_id: str = "new", name: str = "lista.jpg", ctype: str = "image/jpeg"):
    return c.post("/v1/baskets/import-image", files={"file": (name, data, ctype)}, data={"basket_id": basket_id})


def by_row(res: dict) -> dict[int, dict]:
    return {r["row_number"]: r for r in res["rows"]}


def line(res: dict, line_id: int) -> dict:
    return next(x for x in res["basket"]["lines"] if x["line_id"] == line_id)


@pytest.fixture
def listed(llm):
    llm.extraction = LIST
    return llm


def test_a_photo_of_a_list_becomes_basket_lines(chef, listed):
    r = send(chef, png())
    assert r.status_code == 200, r.text
    res = r.json()
    rows = by_row(res)
    assert {n: x["status"] for n, x in rows.items()} == {
        1: "needs_choice",
        2: "needs_amount",
        3: "needs_choice",
        4: "unmatched",
    }
    milk = line(res, rows[1]["line_id"])
    assert milk["source"] == "image" and milk["raw_text"] == "maito 20 l" and milk["confidence"] == "high"
    assert milk["alternatives"] and {o["product_id"] for o in milk["alternatives"]} <= MILKS
    assert (milk["amount"], milk["unit"]) == (20, "L")
    butter = line(res, rows[3]["line_id"])
    assert "464076" in {o["product_id"] for o in butter["alternatives"]}  # B-11: voi 5 kg finds the butter
    light = line(res, rows[2]["line_id"])  # 12 pieces of a milk sold per litre: the litres are asked for
    assert light["confidence"] == "medium" and "Give the amount in L" in rows[2]["message"]["en"]
    napkins = line(res, rows[4]["line_id"])
    assert (
        napkins["raw_text"] == "servetit 500 kpl" and napkins["confidence"] == "low" and napkins["product_id"] is None
    )
    assert res["extraction"] == LIST.model_dump()
    assert res["counts"]["needs_choice"] == 2 and res["counts"]["unmatched"] == 1
    assert res["message_for_user"]["en"].startswith("4 rows: 2 need your choice, 1 needs an amount, 1 not found.")
    assert all("next delivery date" in x["message"]["en"] for x in res["rows"])  # a photo has no dates
    assert listed.calls == [("read_list", "image/png")]  # the type comes from the bytes, not the client's word


def test_a_matched_item_is_priced(chef, llm):
    llm.extraction = ListExtraction.model_validate(
        {
            "handwritten": False,
            "unreadable": [],
            "need_date": None,
            "items": [
                {"raw_text": "Eila voi 5 kg", "name": "Valio Eila voi 4x5 kg", "quantity": 10, "unit": "KG"}
                | {"note": "", "confidence": "high"}
            ],
        }
    )
    res = send(chef, png()).json()
    butter = res["basket"]["lines"][0]
    assert (res["rows"][0]["status"], butter["product_id"], butter["offer"]["qty"]) == ("priced", "464076", 2)


def test_a_date_written_on_the_list_dates_every_line(chef, llm):
    llm.extraction = LIST.model_copy(update={"need_date": "2026-11-16"})  # 'Tilaus ma 16.11.'
    res = send(chef, png()).json()
    assert {x["need_date"] for x in res["basket"]["lines"]} == {"2026-11-16"}
    assert not any("next delivery date" in x["message"]["en"] for x in res["rows"])
    assert "no delivery date" not in res["message_for_user"]["en"]


def test_an_item_outside_the_catalogue_is_not_found_even_without_a_unit(chef, llm):
    # A real read of 'kertakäyttöhanskat 2 ltk' (2 boxes of gloves): no product to price, so not 'needs an amount'.
    gloves = {"raw_text": "kertakäyttöhanskat 2 ltk", "name": "kertakäyttöhanskat", "quantity": 2, "unit": None}
    llm.extraction = ListExtraction.model_validate(
        {
            "handwritten": False,
            "unreadable": [],
            "need_date": None,
            "items": [gloves | {"note": "", "confidence": "high"}],
        }
    )
    res = send(chef, png()).json()
    assert res["rows"][0]["status"] == "unmatched" and res["counts"]["unmatched"] == 1
    assert res["basket"]["lines"][0]["status"] == "unmatched"


def test_a_photo_adds_to_the_basket_in_focus(chef, listed):
    basket_id = send(chef, png()).json()["basket_id"]
    again = send(chef, png(), basket_id=basket_id).json()
    assert again["basket_id"] == basket_id
    assert len(again["basket"]["lines"]) == 4  # the same items again: each reports its line instead
    assert all("already line" in r["message"]["en"] for r in again["rows"])


def test_a_refusal_is_200_with_zero_rows(chef, llm):
    llm.error = LLMRefused("Claude declined")
    r = send(chef, png())
    assert r.status_code == 200
    res = r.json()
    assert res["rows"] == [] and res["reason_code"] == "not_found" and res["basket"]["lines"] == []
    assert res["extraction"] == {"items": [], "handwritten": False, "unreadable": [], "need_date": None}
    assert "No shopping list lines could be read" in res["message_for_user"]["en"]


def test_nothing_readable_is_200_with_zero_rows(chef, llm):
    llm.extraction = ListExtraction(items=[], handwritten=True, unreadable=["the whole page"], need_date=None)
    res = send(chef, png()).json()
    assert res["rows"] == [] and res["extraction"]["unreadable"] == ["the whole page"]
    assert res["message_for_user"]["fi"].startswith("Kuvasta ei saatu luettua")


def test_the_ai_service_unavailable_is_503(chef, llm):
    llm.error = LLMUnavailable("no Anthropic credentials")
    r = send(chef, png())
    assert r.status_code == 503
    assert r.json()["detail"] == "The AI service is unavailable right now. Try again in a moment."
    assert chef.get("/v1/baskets/current").status_code == 404


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"%PDF-1.7 not a photo", 415),
        (b"maito 20 l\nvoi 5 kg\n", 415),
        (b"", 413),
        (png()[:30], 415),  # cut short
        (png(9000, 10), 422),  # wider than the API takes
    ],
)
def test_files_that_are_not_sent_to_claude(chef, llm, data, status):
    r = send(chef, data)
    assert r.status_code == status and r.json()["detail"]
    assert llm.calls == []


def test_an_oversized_upload_is_refused_before_claude(chef, llm):
    big = png() + b"\x00" * (MAX_IMAGE_BYTES + 100)
    r = send(chef, big)
    assert r.status_code == 413 and "7.5 MB" in r.json()["detail"]
    assert llm.calls == []


def test_sign_in_is_required(client, chef, listed):
    assert send(TestClient(client.app), png()).status_code == 401
    session = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    voice = TestClient(client.app)
    r = voice.post(
        "/v1/baskets/import-image",
        files={"file": ("lista.png", png(), "image/png")},
        data={"basket_id": "new"},
        headers=voice_headers(session),
    )
    assert r.status_code == 401
    assert listed.calls == []


def test_another_buyers_basket_is_refused_before_claude(client, chef, listed):
    basket_id = send(chef, png()).json()["basket_id"]
    listed.calls.clear()
    other = TestClient(client.app)
    assert other.post("/api/login", json={"buyer_id": "head_chef"}).status_code == 200
    assert send(other, png(), basket_id=basket_id).status_code == 404
    assert listed.calls == []


def test_an_ordered_basket_is_locked_before_claude(client, settings, chef, listed):
    basket_id = send(chef, png()).json()["basket_id"]
    service(client.app, settings).mark_ordered(BUYERS["chef"], basket_id)
    listed.calls.clear()
    res = send(chef, png(), basket_id=basket_id).json()
    assert res["reason_code"] == "basket_locked" and res["rows"] == []
    assert listed.calls == []
