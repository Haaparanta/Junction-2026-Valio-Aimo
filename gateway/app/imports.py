"""The import pipeline (docs/basket-plan.md M25.2, M28.3): rows from a sheet or a photo become basket lines.

import_rows() takes rows from any reader (sheets.read_sheet, or the photo route's items as SheetRows), matches each
one with match.match_item, turns it into a basket.LineDraft and adds them all through BasketService.add_lines in
one transaction. Then it reports every row: its status, a message {fi, en} and the line it became.

* A row with no product id, GTIN or name is 'invalid' and becomes no line. Any other problem (an unreadable amount
  or date) still gives a line, which then waits for the buyer (needs_amount, or the filled-in date).
* exact or one: the product is pinned. several: the candidates wait for the buyer's choice (needs_choice, or
  needs_amount while the amount is missing). none: an unmatched line that keeps the row's raw text.
* A missing date becomes the next deliverable date (next_delivery_date) and the row's message says so.
* A row identical to a line already in the basket, or to an earlier row, reports that line and says so (the
  duplicate-need rule of add_lines).

The gateway decides every number: statuses and messages come from the priced lines. Cell values and photo text are
data: they reach the line as need_text and raw_text, and no message quotes them.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import get_args

from .basket import LOCKED, BasketService, LineDraft, summary, warnings_for
from .contract import Confidence, ImportResponse, ImportRow, ImportRowStatus, LineSource, ListExtraction, Msg
from .fmt import day_en, day_fi, ids_en, ids_fi, instant, to_helsinki
from .identity import Buyer
from .match import catalogue_entries, match_item
from .sheets import P_NO_ITEM, SheetRow
from .stubs import PRODUCTS, StubState

ROW_STATUSES: list[ImportRowStatus] = list(get_args(ImportRowStatus))
DATE_SEARCH_DAYS = 14  # how far ahead next_delivery_date looks for a pinned product
MAX_AMOUNT = 1_000_000  # LineDraft's upper bound
UNDELIVERABLE = {"CUTOFF_PASSED", "NOT_DELIVERABLE"}

INVALID = Msg(
    fi="Rivillä ei ole tuotenumeroa, GTIN-koodia eikä tuotteen nimeä, joten sitä ei lisätty koriin.",
    en="The row has no product id, GTIN or product name, so it was not added to the basket.",
)
AMOUNT_RANGE = Msg(
    fi="Määrän pitää olla nollaa suurempi ja enintään 1 000 000.",
    en="The amount must be more than zero and at most 1,000,000.",
)
NOTHING_READ = Msg(
    fi="Kuvasta ei saatu luettua yhtään ostoslistan riviä, joten koriin ei lisätty mitään. "
    "Ota tarkempi kuva tai kirjoita tuotteet itse.",
    en="No shopping list lines could be read from the photo, so nothing was added to the basket. "
    "Take a sharper photo or type the products yourself.",
)

STATUS_WORDS: dict[ImportRowStatus, tuple[str, str, str]] = {  # after the count: (fi, en for one, en for many)
    "priced": ("hinnoiteltu", "priced", "priced"),
    "needs_choice": ("odottaa valintaasi", "needs your choice", "need your choice"),
    "needs_amount": ("tarvitsee määrän", "needs an amount", "need an amount"),
    "unmatched": ("ei löytynyt", "not found", "not found"),
    "not_deliverable": ("ei toimitettavissa", "cannot be delivered", "cannot be delivered"),
    "cutoff_passed": ("tilausaika mennyt", "past the cut-off", "past the cut-off"),
    "invalid": ("virheellinen", "invalid", "invalid"),
}


def next_delivery_date(stubs: StubState, as_of: str, product_id: str | None) -> date:
    """The first date from the as-of day + 1 (at most DATE_SEARCH_DAYS ahead) that the pinned product can be
    delivered on, before its cut-off; the as-of day + 1 without a product or when no such date is found."""
    first = to_helsinki(instant(as_of)).date() + timedelta(days=1)
    p = PRODUCTS.get(product_id) if product_id else None
    if p is None:
        return first
    for k in range(DATE_SEARCH_DAYS):
        d = first + timedelta(days=k)
        offer, why = stubs.price_product(p.id, 1.0, p.base_unit, d.isoformat(), as_of)
        if offer is not None or (why is not None and not UNDELIVERABLE & set(why.flags)):
            return d
        if why is None:  # not priced at all: no date will do better
            break
    return first


def _amount(row: SheetRow) -> tuple[float | None, list[Msg]]:
    if row.amount is None:
        return None, []
    value = Decimal(row.amount)
    if not value.is_finite() or value <= 0 or value > MAX_AMOUNT:
        return None, [AMOUNT_RANGE]
    return float(value), []


def _draft(
    row: SheetRow, source: LineSource, confidence: Confidence | None, stubs: StubState, as_of: str
) -> tuple[LineDraft, list[Msg]]:
    """The row's draft and the notes for its message (the filled-in date, an amount out of range)."""
    m = match_item(row.product_id, row.gtin, row.name, entries=catalogue_entries())
    product_id = m.candidates[0].product_id if m.kind in ("exact", "one") else None
    candidates = [c.product_id for c in m.candidates] if m.kind == "several" else []
    amount, notes = _amount(row)
    need_date = row.need_date
    if not need_date:
        d = next_delivery_date(stubs, as_of, product_id)
        need_date = d.isoformat()
        notes.append(
            Msg(
                fi=f"Toimituspäivä puuttui, joten käytin seuraavaa toimituspäivää {day_fi(d)}",
                en=f"The delivery date was missing, so I used the next delivery date, {day_en(d)}.",
            )
        )
    draft = LineDraft(
        source=source,
        need_text=(row.name or row.raw_text or row.product_id or row.gtin)[:200],
        raw_text=row.raw_text,
        confidence=confidence,
        product_id=product_id,
        candidates=candidates,
        amount=amount,
        unit=row.unit,
        need_date=need_date,
    )
    return draft, notes


def _join(*parts: Msg) -> Msg:
    return Msg(fi=" ".join(p.fi for p in parts if p.fi), en=" ".join(p.en for p in parts if p.en))


def _counts(rows: list[ImportRow]) -> dict[str, int]:
    counts = dict.fromkeys(ROW_STATUSES, 0)
    for r in rows:
        counts[r.status] += 1
    return counts


def _head(rows: list[ImportRow], counts: dict[str, int], filled: list[int], duplicates: list[int]) -> Msg:
    n = len(rows)
    parts = [(counts[s], *STATUS_WORDS[s]) for s in ROW_STATUSES if counts[s]]
    fi = f"{'1 rivi' if n == 1 else f'{n} riviä'}: " + ", ".join(f"{k} {w}" for k, w, _, _ in parts) + "."
    en = (
        f"{'1 row' if n == 1 else f'{n} rows'}: "
        + ", ".join(f"{k} {one if k == 1 else many}" for k, _, one, many in parts)
        + "."
    )
    if len(filled) == 1:
        fi += f" Toimituspäivä puuttui riviltä {filled[0]}: käytin seuraavaa toimituspäivää."
        en += f" Row {filled[0]} had no delivery date: I used the next delivery date."
    elif filled:
        fi += f" Toimituspäivä puuttui riveiltä {ids_fi(filled)}: käytin seuraavaa toimituspäivää."
        en += f" Rows {ids_en(filled)} had no delivery date: I used the next delivery date."
    if len(duplicates) == 1:
        fi += f" Rivi {duplicates[0]} oli jo korissa, joten en lisännyt sitä uudelleen."
        en += f" Row {duplicates[0]} was already in the basket, so I did not add it again."
    elif duplicates:
        fi += f" Rivit {ids_fi(duplicates)} olivat jo korissa, joten en lisännyt niitä uudelleen."
        en += f" Rows {ids_en(duplicates)} were already in the basket, so I did not add them again."
    return Msg(fi=fi, en=en)


def import_rows(
    service: BasketService,
    buyer: Buyer,
    basket_id: str,
    rows: Sequence[SheetRow],
    source: LineSource,
    as_of: str,
    confidences: Mapping[int, Confidence] | None = None,
    *,
    extraction: ListExtraction | None = None,
) -> ImportResponse:
    """Match, add and report the rows. confidences: the photo's confidence per row_number. The basket is 'new' or
    the buyer's basket (404 otherwise); an ordered basket answers basket_locked and adds nothing; more lines than a
    basket holds raise 422."""
    confidences = confidences or {}
    usable: list[tuple[SheetRow, LineDraft, list[Msg]]] = []
    report: list[ImportRow] = []
    for row in rows:
        if not (row.product_id or row.gtin or row.name):
            problems = [p for p in row.problems if p != P_NO_ITEM]  # INVALID says it already
            report.append(
                ImportRow(
                    row_number=row.row_number,
                    status="invalid",
                    message=_join(INVALID, *problems),
                    raw_text=row.raw_text,
                )
            )
            continue
        draft, notes = _draft(row, source, confidences.get(row.row_number), service.stubs, as_of)
        usable.append((row, draft, notes))

    added = service.add_lines(buyer, basket_id, [d for _, d, _ in usable], dedupe=True)
    basket = added.basket
    if added.locked:
        return ImportResponse(
            reason_code="basket_locked",
            basket_id=basket.basket_id,
            basket=basket,
            rows=[],
            counts=_counts([]),
            extraction=extraction,
            message_for_user=_join(LOCKED, summary(basket, ordered_note=False)),
            warnings=warnings_for(basket),
        )

    # A line id in `existing` k times was returned for k duplicate rows; one more occurrence is the row that made it.
    seen: dict[int, int] = {}
    filled: list[int] = []
    duplicates: list[int] = []
    for (row, _, notes), line in zip(usable, added.lines, strict=True):
        i = line.line_id
        seen[i] = seen.get(i, 0) + 1
        made = seen[i] == 1 and sum(x.line_id == i for x in added.lines) > added.existing.count(i)
        parts = [line.message]
        if not made:
            duplicates.append(row.row_number)
            parts = [
                Msg(
                    fi=f"Tämä rivi on jo korissa rivinä {i}, joten en lisännyt sitä uudelleen.",
                    en=f"This row is already line {i} of the basket, so I did not add it again.",
                ),
                line.message,
            ]
        if not row.need_date:
            filled.append(row.row_number)
        report.append(
            ImportRow(
                row_number=row.row_number,
                status=line.status,
                message=_join(*parts, *notes, *row.problems),
                line_id=i,
                raw_text=row.raw_text,
            )
        )

    report.sort(key=lambda r: (r.status == "priced", r.row_number))  # rows that need attention first
    counts = _counts(report)
    s = summary(basket)
    head = _head(report, counts, sorted(filled), sorted(duplicates)) if report else NOTHING_READ
    return ImportResponse(
        reason_code=None if report else "not_found",
        basket_id=basket.basket_id,
        basket=basket,
        rows=report,
        counts=counts,
        extraction=extraction,
        message_for_user=_join(head, s),
        warnings=warnings_for(basket),
    )
