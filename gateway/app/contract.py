"""Tool contract (PLAN §5): request and response models shared by REST, MCP and the webhook tools.

Rules that keep the schemas usable as ElevenLabs webhook tool schemas (scripts in agent/):
* request models are flat, every field has a description, and none is Optional (no anyOf);
* money is a decimal string, never a float;
* every response carries status, reason_code, message_for_user {fi, en} and warnings[].
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# UCP checkout statuses for quotes, orders and approvals; the other tools answer "ok".
TradeStatus = Literal["incomplete", "ready_for_complete", "requires_escalation", "completed", "canceled"]
Status = Literal["ok", "incomplete", "ready_for_complete", "requires_escalation", "completed", "canceled"]
ReasonCode = Literal[
    "limit_exceeded",
    "out_of_stock",
    "price_changed",
    "quote_expired",
    "approval_rejected",
    "confirmation_required",
    "cutoff_passed",
    "not_deliverable",
    "unknown_id",
    "not_found",
    "basket_incomplete",  # quote_basket while a line is not priced; the answer lists those lines
    "quote_stale",  # confirm or place_order on a quote whose basket changed after it was made
    "basket_locked",  # a change to an ordered basket; a new basket is needed
]
OfferFlag = Literal[
    "CUTOFF_PASSED",
    "NOT_DELIVERABLE",
    "OUT_OF_STOCK",
    "PARTIAL_STOCK",
    "STOCK_UNTRACKED",
    "UNIT_MISMATCH",
    "SALES_BLOCKED",
    "VARIANT",
    "NET_PRICE",
    "PRICE_NOT_VALID_FOR_DELIVERY_DATE",
]
Money = str  # decimal string with two places, e.g. "1010.00"
ProductId = str
Unit = Literal["L", "KG", "PCS"]


class Msg(BaseModel):
    """A message the agent reads to the buyer, in Finnish and English."""

    fi: str
    en: str


class Envelope(BaseModel):
    status: Status = "ok"
    reason_code: ReasonCode | None = None
    message_for_user: Msg
    warnings: list[str] = Field(default_factory=list)


ID_FIELD = Field(pattern=r"^\d{6}$", description="Six-digit Valio Aimo product id exactly as a tool returned it.")


def _real_date(v: str) -> str:
    """The pattern checks the shape; this rejects dates that do not exist, such as 2026-02-30 (HTTP 422)."""
    if v:
        date.fromisoformat(v)
    return v


IsoDate = Annotated[str, AfterValidator(_real_date)]  # the JSON schema stays a plain string with a pattern


class _Request(BaseModel):
    model_config = ConfigDict(extra="ignore")  # tolerate extra keys from agents; identity never comes from here


# ---- search_products, get_product -------------------------------------------------------------


class SearchRequest(_Request):
    query: str = Field(
        min_length=1, max_length=200, description="The buyer's need in their own words, Finnish or English."
    )
    heads: list[str] = Field(
        default_factory=list,
        description="Product-type heads the name must end with, in Finnish base form, e.g. ['maito', 'maitojuoma'].",
    )
    exclude: list[str] = Field(
        default_factory=list, description="Words that must not appear in the name, e.g. ['kaakao', 'jäätelö']."
    )
    must_claims: list[str] = Field(
        default_factory=list, description="GS1 claims every result must carry, e.g. ['FREE_FROM_LACTOSE']."
    )
    must_not_allergens: list[str] = Field(
        default_factory=list, description="GS1 allergen codes every result must be free of, e.g. ['AM'] for milk."
    )
    temperature: Literal["any", "chilled", "frozen", "ambient"] = Field(
        default="any", description="Temperature class wanted, or 'any'."
    )
    limit: int = Field(default=10, ge=1, le=25, description="Maximum number of products to return.")


class ContentPerUnit(BaseModel):
    value: str
    unit: Literal["L", "KG", "PCS"]
    source: Literal["name", "units", "api_comparison_price", "vote"]
    confidence: Literal["high", "medium", "low"]


class ProductSummary(BaseModel):
    product_id: ProductId
    name_fi: str
    name_en: str | None = None
    brand: str | None = None
    vendor: str | None = None
    category: str
    sales_unit: str
    content_per_unit: ContentPerUnit | None = None
    claims: list[str] = Field(default_factory=list)
    allergens_contains: list[str] = Field(default_factory=list)
    allergen_data: Literal["declared", "unknown"] = "declared"
    temperature_class: Literal["chilled", "frozen", "ambient", "unknown"] = "unknown"


class SearchResponse(Envelope):
    products: list[ProductSummary]
    total_matches: int


class ProductResponse(Envelope):
    product: ProductSummary
    json_ld: dict


# ---- plan_quantity --------------------------------------------------------------------------


class PlanQuantityRequest(_Request):
    product_id: ProductId = ID_FIELD
    amount: float = Field(gt=0, le=1_000_000, description="How much the buyer needs, as a number.")
    unit: Literal["L", "KG", "PCS"] = Field(description="Unit of the amount: litres, kilograms or pieces.")


class PlanQuantityResponse(Envelope):
    product_id: ProductId
    api_unit: str
    content_per_unit: ContentPerUnit
    units_needed: int
    total_content: str
    overshoot: str


# ---- get_offers, find_substitutes -----------------------------------------------------------


class OffersRequest(SearchRequest):
    amount: float = Field(gt=0, le=1_000_000, description="How much the buyer needs, as a number.")
    unit: Literal["L", "KG", "PCS"] = Field(description="Unit of the amount: litres, kilograms or pieces.")
    need_date: IsoDate = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="Delivery date the buyer needs, YYYY-MM-DD (Europe/Helsinki)."
    )
    preference: Literal["cheapest", "greenest", "most_reliable"] = Field(
        default="cheapest", description="How to rank feasible options."
    )
    allow_variants: bool = Field(
        default=False, description="True only if the buyer accepted variants such as coffee milk or portion cups."
    )


class Offer(BaseModel):
    offer_id: str
    tier: Literal["best", "better", "good", "other"]
    product_id: ProductId
    name_fi: str
    api_unit: str
    qty: int
    content_total: str
    unit_price_net: Money
    total_net: Money
    price_per_base_unit: Money
    base_unit: Literal["L", "KG", "PCS"]
    delivery_date: str
    order_by: str
    stock: Literal["untracked", "known", "unknown_terminal", "none"]
    stock_qty: int | None = None
    flags: list[OfferFlag] = Field(default_factory=list)
    explanation: Msg


class NotOffered(BaseModel):
    product_id: ProductId
    name_fi: str
    flags: list[OfferFlag]
    reason: Msg


class OffersResponse(Envelope):
    offer_set_id: str
    need: dict
    as_of: str
    options: list[Offer]
    not_offered: list[NotOffered]
    counts: dict[str, int]


class SubstitutesRequest(_Request):
    product_id: ProductId = ID_FIELD
    amount: float = Field(gt=0, le=1_000_000, description="How much the buyer needs, as a number.")
    unit: Literal["L", "KG", "PCS"] = Field(description="Unit of the amount: litres, kilograms or pieces.")
    need_date: IsoDate = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Delivery date needed, YYYY-MM-DD.")


class Substitute(BaseModel):
    product_id: ProductId
    name_fi: str
    risk_tags: list[Literal["drops_claim", "adds_allergen", "changes_unit", "price_jump", "needs_approval"]]
    offer: Offer | None = None


class SubstitutesResponse(Envelope):
    original_product_id: ProductId
    substitutes: list[Substitute]


# ---- create_quote ---------------------------------------------------------------------------


class CreateQuoteRequest(_Request):
    offer_id: str = Field(
        min_length=3, max_length=80, description="offer_id exactly as returned by get_offers. Never invent or edit it."
    )


class QuoteLine(BaseModel):
    line_id: int
    product_id: ProductId
    name_fi: str
    api_unit: str
    qty: int
    unit_price_net: Money
    line_net: Money
    vat_rate: str
    line_vat: Money
    line_gross: Money
    delivery_date: str


class Evidence(BaseModel):
    api_time_now: str | None = None
    response_sha256: list[str] = Field(default_factory=list)
    stub: bool = False


class Quote(BaseModel):
    quote_id: str
    status: TradeStatus
    buyer_id: str
    lines: list[QuoteLine]
    currency: Literal["EUR"] = "EUR"
    total_net: Money
    total_vat: Money
    total_gross: Money
    vat_rule: Literal["per_line", "per_unit"] = "per_line"
    delivery_date: str  # the earliest line delivery date
    basket_id: str | None = None  # set when quote_basket made this quote
    basket_version: int | None = None  # the basket version it priced; a later edit makes it stale
    issued_at: str
    expires_at: str
    confirmed: bool = False
    confirmed_at: str | None = None
    quote_jws: str | None = None
    evidence: Evidence


class QuoteResponse(Envelope):
    quote_id: str
    quote: Quote
    total_net: Money
    total_gross: Money
    expires_at: str


class ConfirmResponse(Envelope):
    quote_id: str
    confirmed: bool
    confirmation_ref: str | None = None


# ---- place_order, get_order, cancel_order, get_approval ---------------------------------------


class PlaceOrderRequest(_Request):
    quote_id: str = Field(
        min_length=3,
        max_length=80,
        description="quote_id exactly as returned by create_quote. Never invent or edit it.",
    )


class Order(BaseModel):
    order_id: str
    quote_id: str
    status: TradeStatus
    total_net: Money
    total_gross: Money
    delivery_date: str
    approval_id: str | None = None
    approval_url: str | None = None
    created_at: str
    receipt_jws: str | None = None


class OrderResponse(Envelope):
    order_id: str | None = None
    order: Order | None = None
    approval_id: str | None = None
    approval_url: str | None = None
    total_net: Money | None = None


class CancelOrderRequest(_Request):
    reason: str = Field(default="", max_length=200, description="Short reason the buyer gave, if any.")


class Approval(BaseModel):
    approval_id: str
    status: TradeStatus
    order_id: str
    quote_id: str
    reasons: list[str]
    decide_by: str
    approver_role: str


class ApprovalResponse(Envelope):
    approval_id: str
    approval: Approval


# ---- basket: many products, one quote (docs/basket-plan.md M22) -------------------------------

LineSource = Literal["voice", "ui", "import", "image", "dish"]  # voice also covers a typed chat with the agent
LineStatus = Literal["priced", "needs_choice", "needs_amount", "unmatched", "not_deliverable", "cutoff_passed"]
BasketStatus = Literal["open", "ordered"]  # ordered: read-only, its order may be waiting for approval
Confidence = Literal["high", "medium", "low"]

BASKET_ID_DESC = "basket_id exactly as a basket tool returned it. Never invent or edit it."
BASKET_ID_OR_NEW = Field(
    min_length=3,
    max_length=80,
    description="basket_id exactly as a basket tool returned it, or 'new' to start a new basket.",
)
BASKET_ID_FIELD = Field(min_length=3, max_length=80, description=BASKET_ID_DESC)
LINE_ID_FIELD = Field(ge=1, le=10_000, description="line_id exactly as a basket tool returned it.")


class AddToBasketRequest(OffersRequest):
    """add_to_basket: one need (what, how much, by when); the gateway prices it and keeps the alternatives."""

    basket_id: str = BASKET_ID_OR_NEW


class BasketLinePatch(_Request):
    """A change to one line. Without Optional fields, 0 and "" mean "keep the current value"."""

    amount: float = Field(
        default=0, ge=0, le=1_000_000, description="New amount for the whole line, as a number. 0 keeps the amount."
    )
    unit: Literal["", "L", "KG", "PCS"] = Field(
        default="", description="New unit of the amount: L, KG or PCS. Empty keeps the unit."
    )
    need_date: IsoDate = Field(
        default="",
        pattern=r"^(\d{4}-\d{2}-\d{2})?$",
        description="New delivery date, YYYY-MM-DD (Europe/Helsinki). Empty keeps the date.",
    )
    offer_id: str = Field(
        default="",
        max_length=80,
        description="offer_id of one of this line's alternatives, exactly as returned. Empty keeps the offer.",
    )


class UpdateBasketLineRequest(_Request):
    """update_basket_line: the agent's form of BasketLinePatch, with the line named in the body."""

    basket_id: str = BASKET_ID_FIELD
    line_id: int = LINE_ID_FIELD
    amount: float = BasketLinePatch.model_fields["amount"]
    unit: Literal["", "L", "KG", "PCS"] = BasketLinePatch.model_fields["unit"]
    need_date: str = BasketLinePatch.model_fields["need_date"]
    offer_id: str = BasketLinePatch.model_fields["offer_id"]


class BasketLineRequest(_Request):
    """remove_basket_line."""

    basket_id: str = BASKET_ID_FIELD
    line_id: int = LINE_ID_FIELD


class BasketRequest(_Request):
    """get_basket and quote_basket."""

    basket_id: str = BASKET_ID_FIELD


class FlagNote(BaseModel):
    """What one flag means for the buyer, shown on the line's chip and read by the agent."""

    code: OfferFlag
    text: Msg


class BasketLine(BaseModel):
    line_id: int
    source: LineSource
    need_text: str  # the buyer's words, the sheet row's name or the dish ingredient
    raw_text: str | None = None  # exactly as read from a photo or a sheet row
    confidence: Confidence | None = None  # photo lines only
    product_id: ProductId | None = None  # None while unmatched or waiting for a choice
    name_fi: str | None = None
    amount: float | None = None  # None until the buyer gives one (needs_amount)
    unit: Unit | None = None
    need_date: str
    offer: Offer | None = None  # the chosen offer; offer.qty is the number of order units
    alternatives: list[Offer] = Field(default_factory=list)
    status: LineStatus
    flags: list[OfferFlag] = Field(default_factory=list)
    flag_notes: list[FlagNote] = Field(default_factory=list)
    message: Msg  # what the status means and what to do next, e.g. "choose one of 3 matches"
    overshoot: str | None = None  # content ordered beyond the amount, in the line's unit
    vat_rate: str | None = None
    line_vat: Money | None = None
    line_gross: Money | None = None
    notes: list[Msg] = Field(default_factory=list)  # e.g. a dish ingredient's notes


class BasketDish(BaseModel):
    """A dish that plan_dish broke down into lines of this basket."""

    dish: str
    dish_name: Msg
    servings: int
    need_date: str
    batch_note: Msg
    line_ids: list[int]
    assumptions: list[Msg]
    warnings: list[Msg]


class Basket(BaseModel):
    basket_id: str
    buyer_id: str
    status: BasketStatus
    version: int  # goes up on every change; a quote records the version it priced
    lines: list[BasketLine]
    counts: dict[str, int]  # lines per status
    total_net: Money  # priced lines only
    total_vat: Money
    total_gross: Money
    quote_id: str  # the latest quote for this basket, "" when there is none
    quote_stale: bool  # the basket changed after that quote, or the quote is gone
    dishes: list[BasketDish] = Field(default_factory=list)
    created_at: str
    updated_at: str


class BasketResponse(Envelope):
    basket_id: str
    basket: Basket
    line: BasketLine | None = None  # the line this call added or changed


class BasketQuoteResponse(Envelope):
    basket_id: str
    quote_id: str | None = None
    quote: Quote | None = None
    total_net: Money | None = None
    total_gross: Money | None = None
    expires_at: str | None = None
    open_lines: list[int] = Field(default_factory=list)  # with basket_incomplete: the lines to resolve first


# ---- imports: a sheet or a photo of a list (M25, M28) -----------------------------------------

ImportRowStatus = Literal[
    "priced", "needs_choice", "needs_amount", "unmatched", "not_deliverable", "cutoff_passed", "invalid"
]


class ImportRow(BaseModel):
    row_number: int  # as in the sheet (the header row counts), or the item's place on the photo
    status: ImportRowStatus
    message: Msg
    line_id: int | None = None  # None for an invalid row
    raw_text: str  # the row's cells or the photo text, as read


class ListItem(BaseModel):
    """One line of a shopping or order list, as Claude read it from a photo. All fields are required."""

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(description="The line exactly as written in the image.")
    name: str = Field(description="Normalised product name, in Finnish base form when the text is Finnish.")
    quantity: float | None = Field(description="The amount as a number, or null when none is written.")
    unit: Unit | None = Field(description="L, KG or PCS, or null when no unit is written.")
    note: str = Field(description="Anything else written on the line, or an empty string.")
    confidence: Confidence = Field(description="How sure the reading of this line is.")


class ListExtraction(BaseModel):
    """Claude's structured output for a photo of a list (M28)."""

    model_config = ConfigDict(extra="forbid")

    items: list[ListItem] = Field(description="Every list line that was read, in order. Never invent items.")
    handwritten: bool = Field(description="True when the list is handwritten.")
    unreadable: list[str] = Field(description="Parts of the image that could not be read.")


class ImportResponse(Envelope):
    basket_id: str
    basket: Basket
    rows: list[ImportRow]  # rows that need attention first
    counts: dict[str, int]  # rows per status
    extraction: ListExtraction | None = None  # photo imports only


# ---- plan_dish: a dish becomes basket lines (M26, M27) ----------------------------------------

Claim = Literal[
    "FREE_FROM_LACTOSE",
    "FREE_FROM_GLUTEN",
    "VEGAN",
    "VEGETARIAN",
    "FREE_FROM_EGGS",
    "FREE_FROM_SOY",
    "FREE_FROM_WHEAT",
    "LOW_LACTOSE",
]
Allergen = Literal[
    "AM", "AE", "AW", "UW", "GB", "NR", "GO", "AY", "AN", "AP", "AS", "AF", "AC", "UM", "BC", "BM", "AU", "NL"
]


class DishInput(_Request):
    """The dish breakdown prompt's input (docs/briefs/dish-breakdown-prompt.md)."""

    dish: str = Field(
        min_length=1,
        max_length=200,
        description="The finished dish in the buyer's words, Finnish or English, e.g. 'mansikkakakku'.",
    )
    servings: int = Field(ge=1, le=5000, description="Number of portions.")
    need_date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="Delivery date the buyer needs, YYYY-MM-DD (Europe/Helsinki)."
    )
    must_claims: list[Claim] = Field(
        default_factory=list,
        description="GS1 claims the ingredients must carry where they make sense, e.g. ['FREE_FROM_LACTOSE'].",
    )
    must_not_allergens: list[Allergen] = Field(
        default_factory=list,
        description="GS1 allergen codes no ingredient may contain, e.g. ['AM'] only for milk-free or a milk allergy.",
    )
    language: Literal["fi", "en"] = Field(default="fi", description="The language the buyer speaks.")


class PlanDishRequest(DishInput):
    """plan_dish: break a dish down and add every ingredient to a basket."""

    basket_id: str = BASKET_ID_OR_NEW


class DishSearch(BaseModel):
    """search_products fields for one ingredient. The gateway clamps limit and re-adds the input's allergens."""

    model_config = ConfigDict(extra="forbid")

    query: str
    heads: list[str]
    exclude: list[str]
    must_claims: list[Claim]
    must_not_allergens: list[Allergen]
    temperature: Literal["any", "chilled", "frozen", "ambient"]
    limit: int


class DishIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: str
    name: Msg
    role: Literal["main", "secondary", "garnish"]
    amount: float  # for all servings; the gateway checks it is positive
    unit: Unit
    per_serving: float  # recomputed by the gateway
    search: DishSearch
    need_date: str  # overwritten with the input's need_date
    notes: list[Msg]


class DishBreakdown(BaseModel):
    """Claude's structured output for a dish. Extra fields are rejected, so no price or product id gets through."""

    model_config = ConfigDict(extra="forbid")

    dish: str
    dish_name: Msg
    servings: int
    batch_note: Msg
    ingredients: list[DishIngredient]
    assumptions: list[Msg]
    warnings: list[Msg]


class DishResponse(Envelope):
    basket_id: str
    basket: Basket
    dish: BasketDish
