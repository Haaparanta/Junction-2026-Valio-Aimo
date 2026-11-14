"""The catalogue (PLAN M2): products.json streamed into catalog.db, and the compact record read back from it.

Build:  build(products_json, out_db, reliability_csv, carbon_csv) -> coverage report (scripts/build_catalog.py)
Read:   open_catalog(path), get_product(conn, id) -> {record, json_ld}, get_record, json_ld, summary_fields,
        content_for_unit(record, unit)
Codes:  allergen_status(record, code), has_claim(record, claim)
Search: reverse_term(head) for the product_fts.rev_fi suffix index (M4)
"""

from .codes import allergen_status, has_claim
from .content import parse_name, static_content
from .etl import SCHEMA_VERSION, build, iter_products, transform
from .record import (
    content_for_unit,
    digital_link,
    get_product,
    get_record,
    gtin_check_ok,
    json_ld,
    open_catalog,
    summary_fields,
)
from .text import reverse_term, reversed_tokens

__all__ = [
    "SCHEMA_VERSION",
    "allergen_status",
    "build",
    "content_for_unit",
    "digital_link",
    "get_product",
    "get_record",
    "gtin_check_ok",
    "has_claim",
    "iter_products",
    "json_ld",
    "open_catalog",
    "parse_name",
    "reverse_term",
    "reversed_tokens",
    "static_content",
    "summary_fields",
    "transform",
]
