"""The policy engine (PLAN M7.2, findings R-07, G-07): allow, require_approval or deny, decided in code.

evaluate(mandate, quote, context) is pure: everything it needs about the products, the buyer's other open orders and
the diet need comes in `context`, which orders.py builds from the backend (app/backend.py). Each reason is a
'CODE: detail' string in the approval request and the audit log, and the whole decision maps to one reason_code for
the tool answer (PLAN §5: OVER_ORDER_CAP -> limit_exceeded).

Triggers, in the order their reasons are listed:
* deny: no mandate for the caller, a mandate whose org admin signature does not verify (M7.3), a mandate without
  order rights, an allergen or claim that contradicts the diet need;
* require_approval: over the order cap; over the cap per requisition (the buyer's open orders for the same delivery
  date count together, so a need cannot be split under the cap); over the weekly budget; more units on a line than the
  mandate allows; a category or temperature class outside the mandate; a delivery weekday not allowed; a substituted
  line without substitution consent; a net price above list (X-17); a price jump against the buyer's previous price
  for the product; a unit mismatch (UNIT_MISMATCH); allergen data unknown for a known diet need; a mandate where every
  order needs approval (the external agent).

Not yet: OTIF band and delivery reliability (R-03, the stubs carry neither) and partial delivery (an offer is only made
when the full amount can be delivered, so a quote never holds a partial line).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from .contract import Quote, ReasonCode
from .fmt import fi, money
from .mandates import Mandate, verified

Outcome = Literal["allow", "require_approval", "deny"]
PRICE_JUMP_PCT = Decimal(10)  # a unit price more than 10 % above the buyer's previous price needs approval (R-07)
LIMIT_CODES = {"OVER_ORDER_CAP", "OVER_REQUISITION_CAP", "OVER_WEEKLY_BUDGET", "QTY_OVER_MAX"}


@dataclass(frozen=True)
class Reason:
    code: str
    en: str  # the detail, in English: the 'CODE: detail' string
    fi: str  # the same detail in Finnish, for message_for_user

    def __str__(self) -> str:
        return f"{self.code}: {self.en}"


@dataclass(frozen=True)
class LineFacts:
    """One quote line with what the policy needs to know about its product and how it was chosen."""

    line_id: int
    product_id: str
    name_fi: str
    qty: int
    unit_price_net: Decimal
    line_net: Decimal
    delivery_date: date
    category: str = ""
    temperature: str = "unknown"
    allergens: tuple[str, ...] = ()
    allergen_data: Literal["declared", "unknown"] = "declared"
    claims: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()  # the quoted offer's flags, e.g. UNIT_MISMATCH
    substituted: bool = False  # the line's offer came from find_substitutes
    list_price: Decimal | None = None  # the list price when the row has one (X-17)
    previous_price: Decimal | None = None  # the unit price on the buyer's previous open order of this product
    diet_known: bool = False  # True when the need the line was offered for is known
    must_claims: tuple[str, ...] = ()
    must_not_allergens: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenLine:
    """A line of one of the buyer's other open orders (completed, or waiting for approval)."""

    order_id: str
    delivery_date: date
    line_net: Decimal


@dataclass(frozen=True)
class PolicyContext:
    lines: list[LineFacts]
    open_lines: list[OpenLine] = field(default_factory=list)
    mandate_jws: str | None = None  # the mandate's signed token; None: the signed seed of that mandate id (M7.3)


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reasons: list[Reason]

    @property
    def reason_strings(self) -> list[str]:
        return [str(r) for r in self.reasons]

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    @property
    def reason_code(self) -> ReasonCode | None:
        if self.outcome == "deny":
            return "policy_denied"
        if self.outcome == "require_approval":
            return "limit_exceeded" if LIMIT_CODES & set(self.codes) else "approval_required"
        return None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _deny(code: str, en: str, fi_text: str) -> Decision:
    return Decision("deny", [Reason(code, en, fi_text)])


def evaluate(mandate: Mandate | None, quote: Quote, context: PolicyContext) -> Decision:
    """The decision for ordering `quote` under `mandate`. The mandate comes from the authenticated caller only."""
    if mandate is None:
        return _deny("NO_MANDATE", "no mandate covers this caller", "tälle käyttäjälle ei ole valtuutusta")
    if not verified(mandate, context.mandate_jws):  # verified on every evaluation (M7.3)
        return _deny(
            "MANDATE_INVALID",
            "the mandate is not the one the organisation admin signed",
            "valtuutus ei vastaa organisaation pääkäyttäjän allekirjoittamaa",
        )
    if not mandate.orders_allowed:
        return _deny("ORDERS_NOT_ALLOWED", "this mandate does not allow orders", "valtuutus ei salli tilauksia")

    deny: list[Reason] = []
    for x in context.lines:
        if not x.diet_known:
            continue
        hits = sorted(set(x.allergens) & set(x.must_not_allergens))
        missing = sorted(set(x.must_claims) - set(x.claims))
        if hits or missing:
            what = ", ".join([*(f"contains {a}" for a in hits), *(f"lacks {c}" for c in missing)])
            what_fi = ", ".join([*(f"sisältää {a}" for a in hits), *(f"ei ole {c}" for c in missing)])
            deny.append(
                Reason(
                    "ALLERGEN_CONFLICT",
                    f"line {x.line_id} ({x.product_id}) {what}",
                    f"rivi {x.line_id} ({x.product_id}): {what_fi}",
                )
            )
    if deny:
        return Decision("deny", deny)

    reasons: list[Reason] = []
    cap = mandate.order_cap
    total = Decimal(quote.total_net)
    if total > cap:
        reasons.append(
            Reason(
                "OVER_ORDER_CAP",
                f"EUR {money(total)} is above the EUR {money(cap)} order cap",
                f"tilaus {fi(money(total))} € ylittää {fi(money(cap))} euron tilausrajan",
            )
        )

    # The cap per requisition (R-07, G-07): this order's lines and the buyer's other open orders for the same date.
    this_by_date: dict[date, Decimal] = defaultdict(Decimal)
    for x in context.lines:
        this_by_date[x.delivery_date] += x.line_net
    others_by_date: dict[date, Decimal] = defaultdict(Decimal)
    orders_by_date: dict[date, set[str]] = defaultdict(set)
    for o in context.open_lines:
        others_by_date[o.delivery_date] += o.line_net
        orders_by_date[o.delivery_date].add(o.order_id)
    for d in sorted(this_by_date):
        combined = this_by_date[d] + others_by_date[d]
        n = len(orders_by_date[d])
        if n and combined > cap:
            reasons.append(
                Reason(
                    "OVER_REQUISITION_CAP",
                    f"EUR {money(combined)} for delivery on {d.isoformat()}, with {n} other open "
                    f"order{'s' if n > 1 else ''}, is above the EUR {money(cap)} order cap",
                    f"toimitukseen {d.day}.{d.month}. tilataan muiden avointen tilausten kanssa yhteensä "
                    f"{fi(money(combined))} €, mikä ylittää {fi(money(cap))} euron tilausrajan",
                )
            )

    budget = mandate.weekly_budget
    week_this: dict[date, Decimal] = defaultdict(Decimal)
    for x in context.lines:
        week_this[_monday(x.delivery_date)] += x.line_net
    week_others: dict[date, Decimal] = defaultdict(Decimal)
    for o in context.open_lines:
        week_others[_monday(o.delivery_date)] += o.line_net
    for monday in sorted(week_this):
        spent = week_this[monday] + week_others[monday]
        if spent > budget:
            reasons.append(
                Reason(
                    "OVER_WEEKLY_BUDGET",
                    f"EUR {money(spent)} for the week of {monday.isoformat()} is above the EUR {money(budget)} "
                    "weekly budget",
                    f"viikon {monday.day}.{monday.month}. alkaen tilaukset ovat {fi(money(spent))} €, mikä ylittää "
                    f"{fi(money(budget))} euron viikkobudjetin",
                )
            )

    for x in context.lines:
        if x.qty > mandate.max_qty_per_line:
            reasons.append(
                Reason(
                    "QTY_OVER_MAX",
                    f"line {x.line_id} has {x.qty} units, more than the {mandate.max_qty_per_line} allowed",
                    f"rivillä {x.line_id} on {x.qty} yksikköä, enemmän kuin sallitut {mandate.max_qty_per_line}",
                )
            )
    for x in context.lines:
        if mandate.allowed_categories and not any(x.category.startswith(c) for c in mandate.allowed_categories):
            reasons.append(
                Reason(
                    "CATEGORY_NOT_ALLOWED",
                    f"line {x.line_id} is in category {x.category or 'unknown'}, outside the mandate",
                    f"rivin {x.line_id} tuoteryhmä {x.category or 'tuntematon'} ei kuulu valtuutukseen",
                )
            )
        if x.temperature != "unknown" and x.temperature not in mandate.allowed_temperatures:
            reasons.append(
                Reason(
                    "TEMPERATURE_NOT_ALLOWED",
                    f"line {x.line_id} is {x.temperature}, outside the mandate",
                    f"rivin {x.line_id} lämpötilaluokka ({x.temperature}) ei kuulu valtuutukseen",
                )
            )
    for d in sorted({x.delivery_date for x in context.lines}):
        if d.weekday() not in mandate.allowed_delivery_weekdays:
            reasons.append(
                Reason(
                    "DELIVERY_DAY_NOT_ALLOWED",
                    f"delivery on {d.strftime('%A')} {d.isoformat()} is not an allowed delivery day",
                    f"toimituspäivä {d.day}.{d.month}. ei ole sallittu toimituspäivä",
                )
            )
    for x in context.lines:
        if x.substituted and not mandate.substitution_consent:
            reasons.append(
                Reason(
                    "SUBSTITUTION",
                    f"line {x.line_id} ({x.product_id}) is a substitute",
                    f"rivi {x.line_id} ({x.product_id}) on korvaava tuote",
                )
            )
        if x.list_price is not None and x.unit_price_net > x.list_price:
            reasons.append(
                Reason(
                    "NET_ABOVE_LIST",
                    f"line {x.line_id} net price EUR {money(x.unit_price_net)} is above the list price "
                    f"EUR {money(x.list_price)}",
                    f"rivin {x.line_id} nettohinta {fi(money(x.unit_price_net))} € on yli listahinnan "
                    f"{fi(money(x.list_price))} €",
                )
            )
        if x.previous_price and x.unit_price_net > x.previous_price * (1 + PRICE_JUMP_PCT / 100):
            pct = (x.unit_price_net / x.previous_price - 1) * 100
            reasons.append(
                Reason(
                    "PRICE_JUMP",
                    f"line {x.line_id} unit price EUR {money(x.unit_price_net)} is {money(pct)} % above the previous "
                    f"EUR {money(x.previous_price)}",
                    f"rivin {x.line_id} yksikköhinta {fi(money(x.unit_price_net))} € on {fi(money(pct))} % "
                    f"edellistä ({fi(money(x.previous_price))} €) korkeampi",
                )
            )
        if "UNIT_MISMATCH" in x.flags:
            reasons.append(
                Reason(
                    "UNIT_MISMATCH",
                    f"line {x.line_id} ({x.product_id}) is priced in a different unit than the catalogue sells",
                    f"rivin {x.line_id} ({x.product_id}) hintayksikkö eroaa luettelon myyntiyksiköstä",
                )
            )
        if x.diet_known and (x.must_claims or x.must_not_allergens) and x.allergen_data == "unknown":
            reasons.append(
                Reason(
                    "ALLERGEN_DATA_UNKNOWN",
                    f"line {x.line_id} ({x.product_id}) has no allergen data for the diet need",
                    f"rivin {x.line_id} ({x.product_id}) allergeenitiedot puuttuvat, vaikka ruokavalio on annettu",
                )
            )
    if mandate.every_order_needs_approval:
        reasons.append(
            Reason(
                "MANDATE_REQUIRES_APPROVAL",
                "every order under this mandate needs approval",
                "tämän valtuutuksen jokainen tilaus tarvitsee hyväksynnän",
            )
        )
    return Decision("require_approval" if reasons else "allow", reasons)
