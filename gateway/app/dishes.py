"""Dish to basket (docs/basket-plan.md M27.1, M27.4): a finished dish becomes priced basket lines.

plan_dish() is the one path: llm.breakdown(DishInput), then dish.finalize_breakdown (the checks in code, B-12), then
one LineDraft per ingredient (source 'dish', the ingredient's search need, amount, unit and the dish's need_date),
then BasketService.add_lines, which also stores the BasketDish header in the same transaction.

Claude takes 35-51 s for a plan (llm.py), longer than a voice tool may wait, so there are two ways in:
* the screen's dish form calls POST /v1/baskets/dish and waits for plan_dish() itself;
* the voice agent's plan_dish tool calls create_job(), which answers at once with a job. Basket.dish_jobs names the
  job, so the open page sees it as soon as show_basket shows the basket; the page runs it with run_job() inside its
  own request and tells the agent when it is done. A job is claimed atomically (one UPDATE with a row count), so two
  tabs never plan one dish twice, and a run that died is reclaimed after STALE_S seconds.

Dish names, ingredient names and notes are data: they reach the lines as need_text and notes, never as instructions.
"""

import json
import logging
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from fastapi import HTTPException

from .basket import LOCKED, BasketService, LineDraft, LineNeed, not_found, summary, warnings_for
from .contract import (
    Basket,
    BasketDish,
    DishBreakdown,
    DishInput,
    DishJobResponse,
    DishResponse,
    Msg,
    PlanDishRequest,
)
from .dish import finalize_breakdown
from .fmt import ids_en, ids_fi, quoted, to_helsinki
from .identity import Buyer
from .llm import DishPlanner, LLMRefused, LLMUnavailable

log = logging.getLogger(__name__)

STALE_S = 180  # a running job not finished after this long is claimed again (a closed tab, a crash)
MAX_AMOUNT = 1_000_000  # LineDraft's upper bound
AI_UNAVAILABLE = "The AI service is unavailable right now. Try again in a moment."

REFUSED = Msg(
    fi="En pystynyt suunnittelemaan tätä ruokalajia, joten koriin ei lisätty mitään. Kerro ruokalaji tarkemmin.",
    en="I could not plan this dish, so nothing was added to the basket. Please say more about the dish.",
)
NO_INGREDIENTS = Msg(
    fi="Ruokalajista ei saatu aineksia, joten koriin ei lisätty mitään.",
    en="No ingredients came out for this dish, so nothing was added to the basket.",
)
PENDING = Msg(
    fi="Suunnittelen ruokalajin ainekset. Se kestää noin puoli minuuttia; rivit tulevat koriin, kun ne ovat valmiit.",
    en="I am planning the dish's ingredients. It takes about half a minute; the lines appear in the basket when "
    "they are ready.",
)
RUNNING = Msg(
    fi="Ruokalajin suunnittelu on vielä kesken. Rivit tulevat koriin, kun ne ovat valmiit.",
    en="The dish plan is still running. The lines appear in the basket when they are ready.",
)
FAILED_AI = Msg(
    fi="Tekoälypalvelu ei ole juuri nyt käytettävissä, joten ruokalajia ei suunniteltu. Yritä hetken päästä uudelleen.",
    en="The AI service is unavailable right now, so the dish was not planned. Try again in a moment.",
)
FAILED = Msg(
    fi="Ruokalajin suunnittelu epäonnistui, eikä koriin lisätty mitään. Yritä uudelleen.",
    en="Planning the dish failed and nothing was added to the basket. Try again.",
)
BAD_DATE = "The delivery date does not exist. Use YYYY-MM-DD."


def _check_date(need_date: str) -> None:
    try:
        date.fromisoformat(need_date)
    except ValueError:
        raise HTTPException(422, BAD_DATE) from None


def _join(*parts: Msg) -> Msg:
    return Msg(fi=" ".join(p.fi for p in parts if p.fi), en=" ".join(p.en for p in parts if p.en))


def drafts_for(plan: DishBreakdown, need_date: str) -> tuple[list[LineDraft], list[Msg]]:
    """One draft per checked ingredient, and a warning for each one that cannot become a line."""
    drafts: list[LineDraft] = []
    warnings: list[Msg] = []
    for ing in plan.ingredients:
        name_fi = ing.name.fi.strip() or ing.ingredient_id
        if ing.amount > MAX_AMOUNT:
            warnings.append(
                Msg(
                    fi=f"{quoted(name_fi)}: määrä on liian suuri, joten ainesta ei lisätty.",
                    en=f"{quoted(ing.name.en.strip() or name_fi)}: the amount is too large, so it was not added.",
                )
            )
            continue
        s = ing.search
        need = LineNeed(
            query=s.query[:200],
            heads=s.heads,
            exclude=s.exclude,
            must_claims=list(s.must_claims),
            must_not_allergens=list(s.must_not_allergens),
            temperature=s.temperature,
            limit=s.limit,
        )
        drafts.append(
            LineDraft(
                source="dish",
                need_text=name_fi[:200],
                need=need,
                amount=ing.amount,
                unit=ing.unit,
                need_date=need_date,
                notes=ing.notes,
            )
        )
    return drafts, warnings


def _locked(basket: Basket) -> DishResponse:
    return DishResponse(
        reason_code="basket_locked",
        basket_id=basket.basket_id,
        basket=basket,
        message_for_user=_join(LOCKED, summary(basket, ordered_note=False)),
        warnings=warnings_for(basket),
    )


def _nothing(
    baskets: BasketService, buyer: Buyer, target: str, conversation_id: str | None, head: Msg, warnings: list[Msg]
) -> DishResponse:
    """No dish: the basket as it is ('new' starts one, so the answer always names a basket), and why."""
    added = baskets.add_lines(buyer, target, [], conversation_id)
    if added.locked:
        return _locked(added.basket)
    return DishResponse(
        reason_code="not_found",
        basket_id=added.basket.basket_id,
        basket=added.basket,
        dish=None,
        message_for_user=_join(head, *warnings),
        warnings=[w.en for w in warnings] + warnings_for(added.basket),
    )


def plan_dish(
    baskets: BasketService,
    llm: DishPlanner,
    buyer: Buyer,
    req: PlanDishRequest,
    conversation_id: str | None = None,
) -> DishResponse:
    """Break the dish down and add every ingredient to the basket. Raises LLMUnavailable (the route answers 503),
    404 for another buyer's basket, 422 for a date that does not exist or a basket over its line limit."""
    _check_date(req.need_date)
    target = req.basket_id.strip()
    if target.lower() != "new":
        basket = baskets.get(buyer, target)
        if basket.status == "ordered":
            return _locked(basket)  # before the Claude call: nothing could be added anyway
    inp = DishInput(**req.model_dump(include=set(DishInput.model_fields)))
    try:
        plan = finalize_breakdown(inp, llm.breakdown(inp))
    except LLMRefused as e:
        log.info("dish plan refused: %s", e)
        return _nothing(baskets, buyer, target, conversation_id, REFUSED, [])
    drafts, skipped = drafts_for(plan, inp.need_date)
    warnings = [*plan.warnings, *skipped]
    if not drafts:
        return _nothing(baskets, buyer, target, conversation_id, NO_INGREDIENTS, warnings)

    made: list[BasketDish] = []

    def record(c: sqlite3.Connection, basket_id: str, line_ids: list[int]) -> None:
        dish = BasketDish(
            dish=inp.dish,
            dish_name=plan.dish_name,
            servings=inp.servings,
            need_date=inp.need_date,
            batch_note=plan.batch_note,
            line_ids=line_ids,
            assumptions=plan.assumptions,
            warnings=warnings,
        )
        seq = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM basket_dish WHERE basket_id = ?", (basket_id,))
        c.execute(
            "INSERT INTO basket_dish (basket_id, seq, dish, created_at) VALUES (?, ?, ?, ?)",
            (
                basket_id,
                seq.fetchone()[0],
                dish.model_dump_json(),
                to_helsinki(datetime.now(UTC)).isoformat(timespec="seconds"),
            ),
        )
        made.append(dish)

    added = baskets.add_lines(buyer, target, drafts, conversation_id, record=record)
    basket = added.basket
    if added.locked:
        return _locked(basket)
    dish = made[0]
    n, ids = len(dish.line_ids), dish.line_ids
    head = Msg(
        fi=f"Lisäsin ruokalajin {quoted(dish.dish_name.fi)} ({dish.servings} annosta) ainekset koriin: "
        f"{'1 rivi' if n == 1 else f'{n} riviä'}, {'rivi' if n == 1 else 'rivit'} {ids_fi(ids)}.",
        en=f"I added the ingredients of {quoted(dish.dish_name.en)} ({dish.servings} servings) to the basket: "
        f"{'1 line' if n == 1 else f'{n} lines'}, {'line' if n == 1 else 'lines'} {ids_en(ids)}.",
    )
    check = (
        Msg(fi="Tarkista oletukset ja varoitukset.", en="Check the assumptions and the warnings.")
        if dish.assumptions or dish.warnings
        else Msg(fi="", en="")
    )
    return DishResponse(
        basket_id=basket.basket_id,
        basket=basket,
        dish=dish,
        message_for_user=_join(head, check, summary(basket)),
        warnings=[w.en for w in warnings] + warnings_for(basket),
    )


# ---- jobs: the voice path ----------------------------------------------------------------------------------------


def request_key(req: PlanDishRequest) -> str:
    """The normalised request without its basket, so a repeated tool call finds its job."""
    key = {
        "dish": " ".join(req.dish.casefold().split()),
        "servings": req.servings,
        "need_date": req.need_date,
        "must_claims": sorted(set(req.must_claims)),
        "must_not_allergens": sorted(set(req.must_not_allergens)),
        "language": req.language,
    }
    return json.dumps(key, sort_keys=True, ensure_ascii=False)


@contextmanager
def _tx(baskets: BasketService, mode: str = "IMMEDIATE") -> Iterator[sqlite3.Connection]:
    with baskets.store.tx(mode) as c:
        c.row_factory = sqlite3.Row
        yield c


def _job(c: sqlite3.Connection, buyer: Buyer, job_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM dish_job WHERE job_id = ? AND buyer_id = ?", (job_id, buyer.buyer_id)).fetchone()
    if row is None:
        raise not_found("dish job")
    return row


def _respond(row: sqlite3.Row) -> DishJobResponse:
    state = row["state"]
    base = {"job_id": row["job_id"], "basket_id": row["basket_id"], "state": state}
    if state == "done":
        res = DishResponse.model_validate_json(row["result"])
        return DishJobResponse(
            **base,
            status=res.status,
            reason_code=res.reason_code,
            result=res,
            message_for_user=res.message_for_user,
            warnings=res.warnings,
        )
    if state == "failed":
        msg = Msg.model_validate_json(row["message"]) if row["message"] else FAILED
        return DishJobResponse(**base, status="incomplete", message_for_user=msg)
    return DishJobResponse(**base, status="incomplete", message_for_user=PENDING if state == "pending" else RUNNING)


def _find(c: sqlite3.Connection, buyer: Buyer, scope: str, key: str, basket_id: str) -> sqlite3.Row | None:
    """The newest job for this request in this scope that did not fail, on a basket that is still open."""
    return c.execute(
        "SELECT j.* FROM dish_job j JOIN basket b ON b.basket_id = j.basket_id"
        " WHERE j.buyer_id = ? AND j.scope = ? AND j.request_key = ? AND j.state != 'failed' AND b.status = 'open'"
        " AND (? = 'new' OR j.basket_id = ?) ORDER BY j.created_at DESC, j.rowid DESC LIMIT 1",
        (buyer.buyer_id, scope, key, basket_id, basket_id),
    ).fetchone()


def create_job(
    baskets: BasketService, buyer: Buyer, scope: str, conversation_id: str | None, req: PlanDishRequest
) -> DishJobResponse:
    """plan_dish (the agent tool): a pending job on a real basket, at once. The same request in the same scope (the
    conversation, or the buyer's web session) returns the job it made before, unless that job failed."""
    _check_date(req.need_date)
    key, target = request_key(req), req.basket_id.strip()
    target = "new" if target.lower() == "new" else target
    with _tx(baskets, "DEFERRED") as c:
        row = _find(c, buyer, scope, key, target)
    if row is not None:
        return _respond(row)
    if target == "new":  # a voice call reuses the basket it started (add_lines), so a retry finds the same one
        basket = baskets.add_lines(buyer, "new", [], conversation_id).basket
    else:
        basket = baskets.get(buyer, target)
        if basket.status == "ordered":
            return DishJobResponse(
                job_id="",
                basket_id=basket.basket_id,
                state="failed",
                status="incomplete",
                reason_code="basket_locked",
                message_for_user=LOCKED,
            )
    stored = req.model_copy(update={"basket_id": basket.basket_id})
    now = time.time()
    with _tx(baskets) as c:
        row = _find(c, buyer, scope, key, basket.basket_id)  # a twin request may have made it meanwhile
        if row is None:
            for _ in range(5):
                job_id = "J-" + secrets.token_hex(5).upper()
                try:
                    c.execute(
                        "INSERT INTO dish_job (job_id, buyer_id, basket_id, scope, request_key, request, state,"
                        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                        (job_id, buyer.buyer_id, basket.basket_id, scope, key, stored.model_dump_json(), now, now),
                    )
                    break
                except sqlite3.IntegrityError:  # an id collision: draw again
                    continue
            else:
                raise HTTPException(503, "could not create a dish job")
            row = _job(c, buyer, job_id)
    return _respond(row)


def get_job(baskets: BasketService, buyer: Buyer, job_id: str) -> DishJobResponse:
    with _tx(baskets, "DEFERRED") as c:
        return _respond(_job(c, buyer, job_id))


def run_job(baskets: BasketService, llm: DishPlanner, buyer: Buyer, job_id: str) -> DishJobResponse:
    """Run a pending job (or a running one older than STALE_S) inside this request and store its result. A job
    another request is running answers its state at once; a finished job answers its result."""
    claim, now = secrets.token_hex(8), time.time()
    with _tx(baskets) as c:
        row = _job(c, buyer, job_id)
        won = c.execute(
            "UPDATE dish_job SET state = 'running', claim = ?, updated_at = ? WHERE job_id = ?"
            " AND (state = 'pending' OR (state = 'running' AND updated_at < ?))",
            (claim, now, job_id, now - STALE_S),
        ).rowcount
        if won != 1:
            return _respond(row)
    req = PlanDishRequest.model_validate_json(row["request"])
    state, result, message = "done", None, None
    try:
        result = plan_dish(baskets, llm, buyer, req)
    except LLMUnavailable as e:
        log.warning("dish job %s: the AI service is unavailable (%s)", job_id, e)
        state, message = "failed", FAILED_AI
    except HTTPException as e:  # the basket is gone (404), or the dish would overfill it (422)
        state, message = "failed", Msg(fi=FAILED.fi, en=f"{FAILED.en} ({e.detail})")
    except Exception:
        log.exception("dish job %s failed", job_id)
        state, message = "failed", FAILED
    with _tx(baskets) as c:
        c.execute(
            "UPDATE dish_job SET state = ?, result = ?, message = ?, updated_at = ? WHERE job_id = ? AND claim = ?",
            (
                state,
                result.model_dump_json() if result else None,
                message.model_dump_json() if message else None,
                time.time(),
                job_id,
                claim,
            ),
        )
        return _respond(_job(c, buyer, job_id))
