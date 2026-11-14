"""/v1/baskets intake routes: a sheet, a photo of a list, or a dish fills the basket (docs/basket-plan.md M25, M27,
M28).

The screen's routes take the buyer cookie only (voice headers alone get 401). The voice agent's one tool here is
plan_dish, which answers at once with a job that the open page runs (app/dishes.py). Errors are short English
sentences in {detail}, because the screen shows them as they are. Uploads are read only up to their limit plus one
byte, so an oversized file is refused without reading it all; a photo is never stored or logged.

tools.py includes this router before baskets.py's, so these paths win over GET /v1/baskets/{basket_id}.
"""

import logging
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import Response

from ..basket import BasketsDep
from ..contract import DishJobResponse, DishResponse, ImportResponse, ListExtraction, PlanDishRequest
from ..dishes import AI_UNAVAILABLE, create_job, get_job, plan_dish, run_job
from ..identity import CallerDep, SettingsDep, WebBuyerDep
from ..images import MAX_IMAGE_BYTES, ImageError, read_image
from ..imports import import_rows
from ..llm import LLMDep, LLMRefused, LLMUnavailable
from ..sheets import MAX_BYTES, MAX_RAW, SheetError, SheetRow, read_sheet, template_xlsx
from .common import AGENT, tool

log = logging.getLogger(__name__)

router = APIRouter(prefix="/baskets")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BasketIdForm = Annotated[
    str,
    Form(
        pattern=r"^(B-[0-9A-F]{10}|new)$",
        description="basket_id of the basket in focus, exactly as returned, or 'new' to start a basket.",
    ),
]
JobIdPath = Annotated[str, Path(pattern=r"^J-[0-9A-F]{10}$", description="job_id exactly as plan_dish returned it.")]


def _read(upload: UploadFile, limit: int) -> bytes:
    """At most limit + 1 bytes: enough to tell that a file is too large without reading all of it."""
    return upload.file.read(limit + 1)


# ---- a sheet: Excel or CSV (M25.4) ----


@router.post("/import", tags=["ui"])
def import_sheet(
    buyer: WebBuyerDep,
    baskets: BasketsDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="An .xlsx or .csv order list, at most 1 MB.")],
    basket_id: BasketIdForm = "new",
) -> ImportResponse:
    """Every row of the list becomes a basket line, matched and priced by the gateway; rows that need attention
    come first in the report."""
    data = _read(file, MAX_BYTES)
    try:
        rows = read_sheet(file.filename or "", file.content_type or "", data)
    except SheetError as e:
        raise HTTPException(e.status_code, e.message.en) from None
    return import_rows(baskets, buyer, basket_id, rows, "import", settings.as_of)


@router.get("/template.xlsx", tags=["ui"], response_class=Response)
def template() -> Response:
    """The Excel order list template (the same columns as web/public/tilauslista-pohja.csv)."""
    return Response(
        content=template_xlsx(),
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="tilauslista-pohja.xlsx"'},
    )


# ---- a photo of a list (M28) ----


def _rows(extraction: ListExtraction) -> tuple[list[SheetRow], dict[int, str]]:
    """The read items as rows: row_number is the item's place on the list (1-based)."""
    rows: list[SheetRow] = []
    confidences = {}
    for n, item in enumerate(extraction.items, start=1):
        raw = item.raw_text.strip()[:MAX_RAW]
        rows.append(
            SheetRow(
                row_number=n,
                product_id="",
                gtin="",
                name=(item.name.strip() or raw)[:200],
                amount=None if item.quantity is None else Decimal(str(item.quantity)),
                unit=item.unit,
                need_date=None,
                note=item.note.strip()[:200],
                raw_text=raw,
            )
        )
        confidences[n] = item.confidence
    return rows, confidences


@router.post("/import-image", tags=["ui"])
def import_image(
    buyer: WebBuyerDep,
    baskets: BasketsDep,
    settings: SettingsDep,
    llm: LLMDep,
    file: Annotated[UploadFile, File(description="One photo of a shopping or order list: JPEG, PNG, WebP or GIF.")],
    basket_id: BasketIdForm = "new",
) -> ImportResponse:
    """Claude reads the list in the photo; every item becomes a basket line, matched and priced by the gateway.
    The photo is never stored. A refusal or a photo with nothing readable is 200 with zero rows."""
    data = _read(file, MAX_IMAGE_BYTES)
    try:
        media_type, _, _ = read_image(data)  # the type comes from the bytes, never from the client
    except ImageError as e:
        raise HTTPException(e.status_code, e.message) from None
    if basket_id != "new":
        basket = baskets.get(buyer, basket_id)  # 404 before the Claude call
        if basket.status == "ordered":
            return import_rows(baskets, buyer, basket_id, [], "image", settings.as_of)  # basket_locked
    try:
        extraction = llm.read_list(data, media_type)
    except LLMUnavailable as e:
        log.warning("photo import: the AI service is unavailable (%s)", e)
        raise HTTPException(503, AI_UNAVAILABLE) from None
    except LLMRefused as e:
        log.info("photo import: nothing read (%s)", e)
        extraction = ListExtraction(items=[], handwritten=False, unreadable=[])
    rows, confidences = _rows(extraction)
    return import_rows(baskets, buyer, basket_id, rows, "image", settings.as_of, confidences, extraction=extraction)


# ---- a dish (M27) ----


@router.post("/dish", tags=["ui"])
def plan_dish_now(body: PlanDishRequest, buyer: WebBuyerDep, baskets: BasketsDep, llm: LLMDep) -> DishResponse:
    """The screen's dish form: the dish is planned in this request (about 35-51 s) and every ingredient becomes a
    basket line. dish is null with reason_code not_found when nothing could be planned."""
    try:
        return plan_dish(baskets, llm, buyer, body)
    except LLMUnavailable as e:
        log.warning("dish plan: the AI service is unavailable (%s)", e)
        raise HTTPException(503, AI_UNAVAILABLE) from None


@router.post(
    "/dish-jobs",
    operation_id="plan_dish",
    tags=AGENT,
    openapi_extra=tool(
        "Plan a finished dish the buyer names, for the number of portions, and add every ingredient to the basket "
        "as a priced line. It answers at once with a job_id and the basket_id; the plan itself takes about half a "
        "minute on the buyer's screen. Put the buyer's diet in must_claims and must_not_allergens. Use basket_id "
        "'new' only when there is no basket yet. Right away call show_basket with the basket_id and tell the buyer "
        "it takes about half a minute. Wait for the context update that the dish is ready, then call get_basket and "
        "explain the new lines, the assumptions and the warnings. Never state a number that is not in a tool result.",
        filters=["job_id", "basket_id", "state"],
        timeout=15,
        pre_tool_speech="force",
    ),
)
def plan_dish_tool(body: PlanDishRequest, caller: CallerDep, baskets: BasketsDep) -> DishJobResponse:
    scope = (
        caller.conversation_id
        if caller.channel == "voice" and caller.conversation_id
        else f"web:{caller.buyer.buyer_id}"
    )
    return create_job(baskets, caller.buyer, scope, caller.conversation_id, body)


@router.post("/dish-jobs/{job_id}/run", tags=["ui"])
def run_dish_job(job_id: JobIdPath, buyer: WebBuyerDep, baskets: BasketsDep, llm: LLMDep) -> DishJobResponse:
    """The open page runs a plan_dish job in this request: state done (result filled) or failed. A job another
    request is running answers state running at once."""
    return run_job(baskets, llm, buyer, job_id)


@router.get("/dish-jobs/{job_id}", tags=["ui"])
def get_dish_job(job_id: JobIdPath, buyer: WebBuyerDep, baskets: BasketsDep) -> DishJobResponse:
    """A plan_dish job's current state."""
    return get_job(baskets, buyer, job_id)
