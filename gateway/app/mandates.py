"""Buyer mandates (PLAN M7.1, M7.4): what the agent may do for whom, following the AP2 open-mandate pattern.

A mandate is data: the seeds live in mandates.json and are checked against the Mandate model on load, whose JSON Schema
is committed as mandate.schema.json (a test keeps the two in step). The mandate always comes from the authenticated
caller (identity.Buyer.mandate_id, set by the web login, the voice session or, later, the MCP bearer key), never from
tool arguments. Signing mandates with the organisation's admin key (M7.3) is not done yet.
"""

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .identity import Buyer

SEEDS_PATH = Path(__file__).parent / "mandates.json"
SCHEMA_PATH = Path(__file__).parent / "mandate.schema.json"
Weekday = Literal[0, 1, 2, 3, 4, 5, 6]  # Monday = 0, as date.weekday()


class Mandate(BaseModel):
    """One holder's mandate. Money is a decimal string in EUR excl. VAT."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mandate_id: str = Field(description="Stable id; identity.Buyer.mandate_id points here.")
    org_id: str = Field(description="The buyer organisation; approvals stay inside it.")
    holder: str = Field(description="The buyer_id or agent id the mandate belongs to.")
    holder_kind: Literal["person", "agent"] = Field(description="A person (web or voice) or an external AI agent.")
    role: Literal["buyer", "approver"] = Field(description="An approver may also decide the org's approvals.")
    order_cap_eur: str = Field(pattern=r"^\d+\.\d{2}$", description="Per-order cap, applied per requisition (R-07).")
    weekly_budget_eur: str = Field(
        pattern=r"^\d+\.\d{2}$", description="Budget per ISO week of the delivery date, over all open orders."
    )
    allowed_categories: list[str] = Field(
        description="Category code prefixes the holder may buy ('10' covers 10400); an empty list allows any."
    )
    allowed_temperatures: list[Literal["chilled", "frozen", "ambient"]] = Field(
        description="Temperature classes the holder may buy. A product whose class is unknown is not checked."
    )
    max_qty_per_line: int = Field(gt=0, description="Most order units on one line.")
    substitution_consent: bool = Field(description="True: a substituted line needs no approval.")
    allowed_delivery_weekdays: list[Weekday] = Field(description="Delivery weekdays allowed, Monday = 0.")
    approver_role: Literal["approver"] = Field(description="The role that decides this holder's approvals.")
    quotes_allowed: bool = Field(description="The holder may ask for quotes.")
    orders_allowed: bool = Field(description="False: every order is denied.")
    every_order_needs_approval: bool = Field(description="True: even an order within every limit needs approval.")

    @property
    def order_cap(self) -> Decimal:
        return Decimal(self.order_cap_eur)

    @property
    def weekly_budget(self) -> Decimal:
        return Decimal(self.weekly_budget_eur)


@lru_cache
def seeds() -> dict[str, Mandate]:
    """The demo mandates by mandate_id: chef (EUR 500 cap), head chef (approver) and an external agent."""
    raw = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    return {m.mandate_id: m for m in (Mandate.model_validate(x) for x in raw["mandates"])}


def schema() -> dict:
    return Mandate.model_json_schema()


def for_buyer(buyer: Buyer) -> Mandate | None:
    """The authenticated caller's mandate, or None (policy then denies). Another holder's or org's mandate never
    applies."""
    m = seeds().get(buyer.mandate_id)
    return m if m is not None and m.org_id == buyer.org_id and m.holder == buyer.buyer_id else None
