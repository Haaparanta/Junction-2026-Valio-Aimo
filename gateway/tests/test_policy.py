"""Mandates and the policy engine (PLAN M7.1, M7.2, M7.4): one focused test per trigger."""

import json
from datetime import date
from decimal import Decimal

from app.contract import Evidence, Quote, QuoteLine
from app.identity import BUYERS
from app.mandates import SCHEMA_PATH, for_buyer, schema, seeds
from app.policy import LineFacts, OpenLine, PolicyContext, evaluate

CHEF = seeds()["mandate-chef-500"]
HEAD = seeds()["mandate-head-chef"]
AGENT = seeds()["mandate-external-agent"]
MON = date(2026, 11, 16)


def line(net: str = "100.00", *, line_id: int = 1, qty: int = 10, day: date = MON, **facts) -> LineFacts:
    price = facts.pop("price", Decimal(net) / qty)
    return LineFacts(
        line_id=line_id,
        product_id=facts.pop("product_id", "464306"),
        name_fi="maito",
        qty=qty,
        unit_price_net=Decimal(price),
        line_net=Decimal(net),
        delivery_date=day,
        category=facts.pop("category", "10400"),
        temperature=facts.pop("temperature", "chilled"),
        **facts,
    )


def quote_of(*lines: LineFacts) -> Quote:
    total = sum((x.line_net for x in lines), Decimal(0))
    return Quote(
        quote_id="Q-TEST",
        status="ready_for_complete",
        buyer_id="chef",
        lines=[
            QuoteLine(
                line_id=x.line_id,
                product_id=x.product_id,
                name_fi=x.name_fi,
                api_unit="ST",
                qty=x.qty,
                unit_price_net=str(x.unit_price_net),
                line_net=str(x.line_net),
                vat_rate="13.5",
                line_vat="0.00",
                line_gross=str(x.line_net),
                delivery_date=x.delivery_date.isoformat(),
            )
            for x in lines
        ],
        total_net=f"{total:.2f}",
        total_vat="0.00",
        total_gross=f"{total:.2f}",
        delivery_date=min(x.delivery_date for x in lines).isoformat(),
        issued_at="2026-11-14T10:00:00+02:00",
        expires_at="2026-11-14T10:15:00+02:00",
        evidence=Evidence(stub=True),
    )


def run(mandate, *lines: LineFacts, open_lines: list[OpenLine] | None = None):
    return evaluate(mandate, quote_of(*lines), PolicyContext(list(lines), open_lines or []))


# ---- M7.1 mandates ----------------------------------------------------------------------------


def test_the_three_seeds_load_and_match_the_committed_schema():
    assert set(seeds()) == {"mandate-chef-500", "mandate-head-chef", "mandate-external-agent"}
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == schema()
    assert (CHEF.order_cap_eur, CHEF.role, HEAD.role) == ("500.00", "buyer", "approver")
    assert AGENT.holder_kind == "agent" and AGENT.quotes_allowed and AGENT.every_order_needs_approval


def test_the_mandate_comes_from_the_authenticated_buyer_only():
    assert for_buyer(BUYERS["chef"]) == CHEF
    assert for_buyer(BUYERS["head_chef"]) == HEAD
    # A buyer pointing at another holder's mandate gets none (and policy then denies).
    from dataclasses import replace

    assert for_buyer(replace(BUYERS["chef"], mandate_id="mandate-head-chef")) is None
    assert run(None, line()).codes == ["NO_MANDATE"] and run(None, line()).outcome == "deny"


# ---- M7.2 triggers ----------------------------------------------------------------------------


def test_within_every_limit_is_allowed():
    d = run(CHEF, line("400.00"))
    assert (d.outcome, d.reasons, d.reason_code) == ("allow", [], None)


def test_over_the_order_cap():
    d = run(CHEF, line("1010.00", qty=1000))
    assert d.outcome == "require_approval" and d.reason_code == "limit_exceeded"
    assert d.reason_strings == ["OVER_ORDER_CAP: EUR 1010.00 is above the EUR 500.00 order cap"]


def test_the_cap_applies_per_requisition():
    first = [OpenLine("O-1", MON, Decimal("400.00"))]
    d = run(CHEF, line("400.00"), open_lines=first)
    assert d.codes == ["OVER_REQUISITION_CAP"] and d.reason_code == "limit_exceeded"
    assert "EUR 800.00 for delivery on 2026-11-16, with 1 other open order" in d.reason_strings[0]
    # Another delivery date is another requisition.
    assert run(CHEF, line("400.00", day=date(2026, 11, 17)), open_lines=first).outcome == "allow"


def test_over_the_weekly_budget():
    week = [OpenLine(f"O-{i}", date(2026, 11, 16 + i), Decimal("450.00")) for i in range(4)]  # Mon-Thu: 1,800
    d = run(CHEF, line("300.00", day=date(2026, 11, 20)), open_lines=week)  # Fri
    assert d.codes == ["OVER_WEEKLY_BUDGET"] and d.reason_code == "limit_exceeded"
    assert "EUR 2100.00 for the week of 2026-11-16" in d.reason_strings[0]
    assert run(CHEF, line("300.00", day=date(2026, 11, 23)), open_lines=week).outcome == "allow"  # next week


def test_more_units_than_the_mandate_allows():
    d = run(CHEF, line("400.00", qty=2500))
    assert d.codes == ["QTY_OVER_MAX"]


def test_a_category_or_temperature_outside_the_mandate():
    assert run(AGENT, line("100.00", category="41510", temperature="ambient")).codes[:1] == ["CATEGORY_NOT_ALLOWED"]
    assert "TEMPERATURE_NOT_ALLOWED" in run(AGENT, line("100.00", temperature="frozen")).codes
    assert run(CHEF, line("100.00", temperature="unknown")).outcome == "allow"  # unknown is not checked


def test_a_delivery_weekday_not_allowed():
    d = run(CHEF, line("100.00", day=date(2026, 11, 21)))  # a Saturday
    assert d.codes == ["DELIVERY_DAY_NOT_ALLOWED"] and d.reason_code == "approval_required"
    assert run(HEAD, line("100.00", day=date(2026, 11, 21))).outcome == "allow"  # Saturday is in the head chef's


def test_a_substituted_line():
    assert run(CHEF, line(substituted=True)).codes == ["SUBSTITUTION"]
    assert run(HEAD, line(substituted=True)).outcome == "allow"  # the head chef's mandate consents


def test_a_net_price_above_list():
    d = run(CHEF, line("180.60", qty=10, list_price=Decimal("14.65")))  # X-17: 461643, 18.06 vs 14.65
    assert d.codes == ["NET_ABOVE_LIST"]
    assert run(CHEF, line("100.00", qty=10, list_price=Decimal("12.00"))).outcome == "allow"


def test_a_price_jump_against_the_previous_price():
    d = run(CHEF, line("111.10", qty=100, previous_price=Decimal("1.01")))  # 1.111 is exactly +10 %: not above
    assert d.outcome == "allow"
    d = run(CHEF, line("112.00", qty=100, previous_price=Decimal("1.01")))  # 1.12: +10.9 %
    assert d.codes == ["PRICE_JUMP"] and "10.89 % above the previous EUR 1.01" in d.reason_strings[0]


def test_a_unit_mismatch():
    assert run(CHEF, line(flags=("UNIT_MISMATCH", "STOCK_UNTRACKED"))).codes == ["UNIT_MISMATCH"]


def test_allergen_data_unknown_for_a_known_diet_need():
    unknown = {"allergen_data": "unknown", "product_id": "461755"}
    d = run(CHEF, line(**unknown, diet_known=True, must_not_allergens=("AM",)))
    assert d.codes == ["ALLERGEN_DATA_UNKNOWN"]
    assert run(CHEF, line(**unknown)).outcome == "allow"  # no diet need known: nothing to check against
    assert run(CHEF, line(**unknown, diet_known=True)).outcome == "allow"  # a need without diet constraints


def test_an_allergen_contradiction_is_denied():
    d = run(CHEF, line(allergens=("AM",), diet_known=True, must_not_allergens=("AM",)))
    assert (d.outcome, d.codes, d.reason_code) == ("deny", ["ALLERGEN_CONFLICT"], "policy_denied")
    lacks = run(CHEF, line(diet_known=True, must_claims=("FREE_FROM_LACTOSE",)))
    assert lacks.outcome == "deny" and "lacks FREE_FROM_LACTOSE" in lacks.reason_strings[0]


def test_every_order_of_the_external_agent_needs_approval():
    d = run(AGENT, line("10.00"))
    assert (d.outcome, d.codes) == ("require_approval", ["MANDATE_REQUIRES_APPROVAL"])
