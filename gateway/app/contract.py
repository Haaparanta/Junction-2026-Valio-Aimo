"""Tool contract (PLAN §5): request and response models shared by REST, MCP and the webhook tools.

Rules that keep the schemas usable as ElevenLabs webhook tool schemas (scripts in agent/):
* request models are flat, every field has a description, and none is Optional (no anyOf);
* money is a decimal string, never a float;
* every response carries status, reason_code, message_for_user {fi, en} and warnings[].
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    need_date: str = Field(
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
    need_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Delivery date needed, YYYY-MM-DD.")


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
    delivery_date: str
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
