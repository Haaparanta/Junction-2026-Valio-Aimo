"""Offer normaliser and as-of clock (PLAN M3.3, M3.4): table-driven over X-01..X-20 of docs/data-and-api-findings.md.

The entries are response snippets in the exact shapes of A-02, A-05 and A-10; amounts, units, cut-offs and prices are
the observed values of the cited ids.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from app.clients.valio import ApiResult, RejectedId
from app.offers_model import (
    _EuHelsinki,
    classify_amount,
    clock_from_settings,
    fixed_clock,
    local_date,
    normalise_offer,
    normalise_offers,
    parse_api_time,
)
from app.quantity import CatalogUnits

SAT_10 = fixed_clock("2026-11-14T10:00:00+02:00")  # the demo clock
SUN_1630 = fixed_clock("2026-11-15T16:30:00+02:00")
SUN_18 = fixed_clock("2026-11-15T18:00:00+02:00")
STOCK_SUN = "2026-11-15T17:00:00+0200"
STOCK_FRI = "2026-11-13T13:00:00+0200"
TERMINAL_THU = "2026-11-12T15:00:00+0200"


def avail(pid, model="Stock", closing=STOCK_SUN, amount=9999999999.0, unit="ST", day="2026-11-16", block=False):
    line = {"salesBlock": block, "availableAmount": amount, "salesUnit": unit}
    if day is not None:
        line["availableDate"] = day
    return {
        "productId": pid,
        "closingTime": closing,
        "salesBlock": block,
        "logisticModel": model,
        "scheduleLines": [line],
    }


def no_lines(pid):
    return {"productId": pid, "salesBlock": False, "scheduleLines": []}


def window(value, frm="2026-01-01T00:00:00+0200", to="9999-12-31T00:00:00+0200"):
    return {"value": value, "validFrom": frm, "validTo": to, "currency": "EUR"}


def price(pid, net, lst=None, comp=None, unit="L", rate=13.5, net_found=False, to="9999-12-31T00:00:00+0200"):
    entry = {
        "productId": pid,
        "quantity": 1.0,
        "catalogPrice": {**window(net, to=to), "valueWithTax": round(net * (1 + rate / 100), 2)},
        "tax": {"taxRate": rate, "taxValue": 0.0},
        "listPrice": window(lst if lst is not None else round(net / 0.85, 2)),
        "netPriceFound": net_found,
        "error": False,
    }
    if comp is not None:
        entry["comparisonPrice"] = window(comp)
        entry["comparisonUnit"] = unit
    return entry


def unknown_price(pid):
    return {"productId": pid, "quantity": 1.0, "netPriceFound": False, "error": True}


def cat(pid, sales_unit, base_unit=None, units=None, **kw):
    return CatalogUnits(
        product_id=pid, sales_unit=sales_unit, base_unit=base_unit or sales_unit, units=units or {}, **kw
    )


MILK = price("464306", 1.01, 1.44, 1.01, net_found=True, to="2026-12-31T00:00:00+0200")

# (case, product id, availability entry, price entry, options, expected feasibility, flags that must be present)
CASES = [
    (
        "X-01 terminal cut-off passed",
        "463038",
        avail("463038", "Terminal", TERMINAL_THU, 999999.0, "KI"),
        price("463038", 31.31, 36.83, 1.57),
        {},
        "cutoff_passed",
        {"CUTOFF_PASSED", "STOCK_UNKNOWN_TERMINAL"},
    ),
    (
        "X-02 stock with the Friday cut-off",
        "474284",
        avail("474284", closing=STOCK_FRI, amount=83.0, unit="KI"),
        price("474284", 20.0),
        {},
        "cutoff_passed",
        {"CUTOFF_PASSED"},
    ),
    (
        "X-03 six-day supplier cut-off",
        "466869",
        avail("466869", "Terminal", "2026-11-10T14:00:00+0200", 999999.0),
        price("466869", 5.0),
        {},
        "cutoff_passed",
        {"CUTOFF_PASSED"},
    ),
    ("X-04 need date before Monday", "464306", avail("464306"), MILK, {"need_date": "2026-11-15"}, "late", {"LATE"}),
    (
        "X-05 need date after Monday, terminal",
        "463038",
        avail("463038", "Terminal", TERMINAL_THU, 999999.0, "KI"),
        price("463038", 31.31),
        {"need_date": "2026-11-20"},
        "orderable",
        {"CUTOFF_ESTIMATED"},
    ),
    (
        "X-06 clock past Sun 17:00",
        "464306",
        avail("464306"),
        MILK,
        {"as_of": SUN_18},
        "cutoff_passed",
        {"CUTOFF_PASSED", "STOCK_UNTRACKED"},
    ),
    (
        "X-06 inside the approval buffer",
        "464306",
        avail("464306"),
        MILK,
        {"as_of": SUN_1630},
        "cutoff_too_close",
        {"CUTOFF_TOO_CLOSE"},
    ),
    (
        "X-07 not deliverable yet priced",
        "464440",
        no_lines("464440"),
        price("464440", 0.88, comp=1.76),
        {},
        "not_deliverable",
        {"NOT_DELIVERABLE"},
    ),
    (
        "X-08 sales block, December",
        "463989",
        avail("463989", "Terminal", "2026-11-13T12:30:00+0200", 999999.0, day="2026-12-30", block=True),
        price("463989", 3.32, comp=15.51, unit="KG"),
        {},
        "sales_blocked",
        {"SALES_BLOCKED", "LATE"},
    ),
    (
        "X-09 out of stock",
        "461098",
        avail("461098", amount=0.0, unit="PAK", day=None),
        price("461098", 3.64),
        {},
        "out_of_stock",
        {"OUT_OF_STOCK"},
    ),
    (
        "X-10 partial stock",
        "469363",
        avail("469363", amount=384.0),
        price("469363", 2.48, comp=2.48),
        {"qty_needed": 1000},
        "partial",
        {"PARTIAL_STOCK"},
    ),
    (
        "X-11 almost no stock",
        "460509",
        avail("460509", amount=1.0),
        price("460509", 2.0),
        {"qty_needed": 2},
        "partial",
        {"PARTIAL_STOCK"},
    ),
    ("X-12 untracked 9999999999", "464306", avail("464306"), MILK, {}, "orderable", {"STOCK_UNTRACKED", "NET_PRICE"}),
    (
        "X-12 untracked 666666666 KI",
        "463779",
        avail("463779", amount=666666666.0, unit="KI"),
        price("463779", 10.71),
        {"catalog": cat("463779", "KI", "ST", {"KI": 15, "ST": 1})},
        "orderable",
        {"STOCK_UNTRACKED"},
    ),
    (
        "X-12 untracked 39999999 KI",
        "461294",
        avail("461294", amount=39999999.0, unit="KI"),
        price("461294", 9.0),
        {"catalog": cat("461294", "KI", "ST", {"KI": 250})},
        "orderable",
        {"STOCK_UNTRACKED"},
    ),
    (
        "X-13 exact stock, lot 10",
        "462150",
        avail("462150", amount=43.0, unit="KG"),
        price("462150", 14.11, 16.6, 14.11, "KG"),
        {},
        "orderable",
        set(),
    ),
    (
        "X-14 API unit differs",
        "465244",
        avail("465244", "Terminal", TERMINAL_THU, 999999.0, "KI"),
        price("465244", 6.22, 7.32, 2.07),
        {"catalog": cat("465244", "ST", units={"KI": 6, "ST": 1})},
        "cutoff_passed",
        {"UNIT_MISMATCH", "CUTOFF_PASSED"},
    ),
    (
        "X-15 catch weight, frozen, past cut-off",
        "460675",
        avail("460675", "Terminal", "2026-11-12T13:00:00+0200", 999999.0, "KG"),
        price("460675", 29.17, comp=29.17, unit="KG"),
        {"catalog": cat("460675", "KG", units={"KG": 1, "KI": 10}, allowed_lot_size=Decimal(10), variable_unit=True)},
        "cutoff_passed",
        {"CATCH_WEIGHT", "CUTOFF_PASSED"},
    ),
    (
        "X-16 contract price expired",
        "464306",
        avail("464306"),
        MILK,
        {"need_date": "2027-01-04"},
        "orderable",
        {"PRICE_NOT_VALID_FOR_DELIVERY_DATE", "CUTOFF_ESTIMATED", "NET_PRICE"},
    ),
    (
        "X-17 net above list",
        "461643",
        avail("461643", amount=15.0),
        price("461643", 18.06, 14.65, 3.61, net_found=True),
        {},
        "orderable",
        {"NET_ABOVE_LIST", "NET_PRICE"},
    ),
    (
        "X-18 very deep discount",
        "464818",
        avail("464818", "Terminal", TERMINAL_THU, 999999.0, "PAK"),
        price("464818", 6.20, 38.22, net_found=True, rate=25.5),
        {},
        "cutoff_passed",
        {"DEEP_DISCOUNT", "NET_PRICE", "NO_COMPARISON_PRICE"},
    ),
    (
        "X-19 deposit not priced",
        "461051",
        avail("461051", amount=40.0, unit="KI"),
        price("461051", 37.77, rate=25.5),
        {
            "catalog": cat(
                "461051", "KI", "ST", {"KI": 24, "ST": 1}, deposits=[{"material": "4", "unit": "ST", "quantity": 24}]
            )
        },
        "orderable",
        {"DEPOSIT_NOT_PRICED"},
    ),
    ("X-19 deposit code as an id", "4", no_lines("4"), unknown_price("4"), {}, "unknown_id", {"UNKNOWN_ID"}),
    ("X-20 unknown id", "999999", no_lines("999999"), unknown_price("999999"), {}, "unknown_id", {"UNKNOWN_ID"}),
    ("X-20 out of range", "477546", no_lines("477546"), unknown_price("477546"), {}, "unknown_id", {"UNKNOWN_ID"}),
    ("X-20 not digits", "abc", no_lines("abc"), unknown_price("abc"), {}, "unknown_id", {"UNKNOWN_ID"}),
]


@pytest.mark.parametrize(
    ("pid", "availability", "price_entry", "opts", "feasibility", "flags"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_exception_catalogue(pid, availability, price_entry, opts, feasibility, flags):
    opts = {"as_of": SAT_10, "need_date": "2026-11-16", **opts}
    offer = normalise_offer(pid, availability, price_entry, **opts)
    assert offer.feasibility == feasibility
    assert flags <= set(offer.flags), offer.flags


def test_headline_offer_464306():
    offer = normalise_offer(
        "464306", avail("464306"), MILK, as_of=SAT_10, need_date="2026-11-16", evidence=["ab", "cd"]
    )
    assert offer.unit == "ST" and offer.unit_source == "api"
    assert offer.qty_kind == "untracked" and offer.qty is None  # never shown as a number (X-12)
    assert offer.order_by == datetime(2026, 11, 15, 17, tzinfo=ZoneInfo("Europe/Helsinki"))
    assert offer.approve_by == datetime(2026, 11, 15, 16, tzinfo=ZoneInfo("Europe/Helsinki"))
    assert not offer.cutoff_passed and not offer.blocked
    assert offer.price.net == Decimal("1.01") and offer.price.gross == Decimal("1.15")
    assert offer.price.valid_to == date(2026, 12, 31) and offer.price.discount_pct == Decimal("29.9")
    assert offer.validity == "valid"
    assert offer.evidence == ["ab", "cd"]
    dumped = offer.model_dump(mode="json", by_alias=True)
    for key in (
        "unit",
        "qtyKind",
        "qty",
        "availableDate",
        "orderBy",
        "cutoffPassed",
        "blocked",
        "price",
        "validity",
        "flags",
    ):
        assert key in dumped
    assert dumped["orderBy"] == "2026-11-15T17:00:00+02:00"


def test_cutoff_by_the_as_of_clock():
    """M3.3: at Sat 14.11 10:00 464306 is open; at Sun 18:00 it is CUTOFF_PASSED."""
    open_ = normalise_offer("464306", avail("464306"), MILK, as_of=SAT_10)
    closed = normalise_offer("464306", avail("464306"), MILK, as_of=SUN_18)
    assert open_.feasibility == "orderable" and not open_.cutoff_passed
    assert closed.feasibility == "cutoff_passed" and closed.cutoff_passed
    # the same instant in UTC: 15:30Z is 17:30 in Helsinki, past the cut-off
    utc = normalise_offer("464306", avail("464306"), MILK, as_of=datetime(2026, 11, 15, 15, 30, tzinfo=UTC))
    assert utc.cutoff_passed and utc.as_of.utcoffset().total_seconds() == 7200


def test_estimated_cutoff_keeps_the_lead_time():
    """F-05: for Fri 20.11, Terminal Mon 16.11 15:00 and Stock Thu 19.11 17:00, both labelled estimated."""
    hel = ZoneInfo("Europe/Helsinki")
    term = normalise_offer("463038", avail("463038", "Terminal", TERMINAL_THU, 999999.0, "KI"), None,
                           as_of=SAT_10, need_date=date(2026, 11, 20))  # fmt: skip
    stock = normalise_offer("464306", avail("464306"), MILK, as_of=SAT_10, need_date="2026-11-20")
    assert term.order_by == datetime(2026, 11, 16, 15, tzinfo=hel) and term.order_by_estimated
    assert stock.order_by == datetime(2026, 11, 19, 17, tzinfo=hel) and stock.order_by_estimated
    assert term.validity == "no_price" and "NO_PRICE" in term.flags


def test_unit_falls_back_to_the_catalogue_without_lines():
    offer = normalise_offer("464440", no_lines("464440"), None, as_of=SAT_10, catalog=cat("464440", "ST"))
    assert (offer.unit, offer.unit_source, offer.qty_kind) == ("ST", "catalog", "none")


def test_missing_entry_is_not_the_apis_empty_answer():
    offer = normalise_offer("464306", None, MILK, as_of=SAT_10)
    assert offer.feasibility == "not_deliverable"
    assert {"NOT_DELIVERABLE", "NO_AVAILABILITY_DATA"} <= set(offer.flags)


@pytest.mark.parametrize(
    ("amount", "model", "unit", "units", "expected"),
    [
        (999999.0, "Terminal", "KI", {"KI": 400}, ("terminal", None)),  # never scaled by unit (A-05)
        (0.0, "Stock", "PAK", {}, ("zero", Decimal(0))),
        (9999999999.0, "Stock", "ST", {}, ("untracked", None)),
        (3999999999.0, "Stock", "KI", {"KI": 2.5}, ("untracked", None)),
        (540540540.0, "Stock", "KI", {"KI": 18.5}, ("untracked", None)),
        (49999999.0, "Stock", "KI", {"KI": 200}, ("untracked", None)),  # a 1e8 threshold would misread this
        (35714285.0, "Stock", "KI", {"KI": 280}, ("untracked", None)),
        (68293.0, "Stock", "ST", {}, ("exact", Decimal("68293.0"))),  # largest real amount seen
        (42.0, "Stock", "ST", {}, ("exact", Decimal("42.0"))),
    ],
)
def test_classify_amount(amount, model, unit, units, expected):
    assert classify_amount(amount, model, unit, cat("x", unit, "ST", units)) == expected


def test_normalise_offers_from_api_results():
    def result(endpoint, entries, rejected=()):
        return ApiResult(
            endpoint=endpoint, customer="123", requested_date="2026-11-16", entries=entries,
            entry_evidence={k: f"{endpoint}-hash" for k in entries}, evidence=[], rejected=list(rejected),
        )  # fmt: skip

    bad = RejectedId(raw="abc", reason="not_six_digits")
    a = result("availability", {"464306": avail("464306"), "464440": no_lines("464440")}, [bad])
    p = result("price", {"464306": MILK, "464440": price("464440", 0.88)}, [bad])
    offers = normalise_offers(a, p, as_of=SAT_10)
    assert [(o.product_id, o.feasibility) for o in offers] == [
        ("464306", "orderable"),
        ("464440", "not_deliverable"),
        ("abc", "unknown_id"),
    ]
    assert offers[0].evidence == ["availability-hash", "price-hash"]
    assert offers[0].need_date == date(2026, 11, 16)


# ---- time parsing and the clock -------------------------------------------------------------


def test_parse_api_times():
    assert parse_api_time("2026-11-15T17:00:00+0200").utcoffset().total_seconds() == 7200
    assert parse_api_time("1900-01-01T00:00:00+013949").utcoffset().total_seconds() == 5989  # A-14
    assert local_date("2026-12-31T00:00:00+0200") == date(2026, 12, 31)
    assert local_date("2026-09-01T00:00:00+0300") == date(2026, 9, 1)  # summer offset, still the local date


def test_clock_from_settings():
    class S:
        as_of = "2026-11-14T10:00:00+02:00"

    assert clock_from_settings(S())() == datetime(2026, 11, 14, 10, tzinfo=ZoneInfo("Europe/Helsinki"))

    class Live:
        as_of = ""

    assert clock_from_settings(Live())().tzinfo is not None


@pytest.mark.parametrize(
    "utc",
    [
        datetime(2026, 1, 15, 12, tzinfo=UTC),
        datetime(2026, 3, 29, 0, 59, tzinfo=UTC),
        datetime(2026, 3, 29, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 1, 12, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 59, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),  # 03:30 summer time
        datetime(2026, 10, 25, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),  # 03:30 again, winter time (fold 1)
        datetime(2026, 11, 15, 15, tzinfo=UTC),
    ],
)
def test_fallback_timezone_matches_the_tz_database(utc):
    real = utc.astimezone(ZoneInfo("Europe/Helsinki"))
    fallback = utc.astimezone(_EuHelsinki())
    assert fallback.replace(tzinfo=None) == real.replace(tzinfo=None)
    assert fallback.utcoffset() == real.utcoffset()
