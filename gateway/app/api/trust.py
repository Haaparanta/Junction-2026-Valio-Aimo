"""Verifiable trust (PLAN M6.3, M8.5): the public signing keys.

GET /.well-known/jwks.json serves the gateway key (quotes and order receipts) and the organisation admin key
(mandates); scripts/verify_quote.py checks a quote or a receipt against it.
"""

from fastapi import APIRouter

from .. import signing

router = APIRouter()


@router.get("/.well-known/jwks.json", tags=["trust"])
def jwks() -> dict:
    """The public ES256 keys (JWK Set): the gateway key first, then the org admin key. kid is each key's RFC 7638
    thumbprint."""
    return signing.keys().jwks()
