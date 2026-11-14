"""Verify a signed quote (PLAN M6.3) or an order's signed receipt (M8.5) against the gateway's JWKS.

    uv run python scripts/verify_quote.py quote.json
    uv run python scripts/verify_quote.py http://localhost:8000/v1/quotes/Q-1234567890 --cookie <va_session>
    uv run python scripts/verify_quote.py order.json --jwks https://example.org/.well-known/jwks.json

The input is a quote, an order, or a tool answer that holds one ({"quote": ...} or {"order": ...}). The JWKS defaults
to /.well-known/jwks.json on the input URL's origin, else http://localhost:8000. Independent of the gateway code on
purpose: only joserfc and rfc8785, ES256 pinned.

* A quote verifies when its quote_jws has a good ES256 signature from a JWKS key and its payload is exactly the RFC 8785
  canonical JSON of the quote without quote_jws, status, confirmed and confirmed_at. Any other change fails.
* A receipt verifies when receipt_jws has a good signature and names the same order id, quote, totals, delivery date
  and completion time as the order.

Exit status 0 when it verifies, 1 when it does not, 2 on a usage or fetch error.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import rfc8785
from joserfc import jws
from joserfc.errors import JoseError
from joserfc.jwk import ECKey, KeySet

QUOTE_UNSIGNED = ("quote_jws", "status", "confirmed", "confirmed_at")
RECEIPT_FIELDS = ("order_id", "quote_id", "total_net", "total_gross", "delivery_date", "completed_at")


def fetch(source: str, cookie: str | None = None) -> dict:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"Accept": "application/json"})
        if cookie:
            req.add_header("Cookie", f"va_session={cookie}")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def keyset(jwks: dict, typ: str) -> KeySet:
    """The P-256 keys that may sign `typ` (the gateway's JWKS names it in each key's `typ` member)."""
    keys = []
    for k in jwks.get("keys", []):
        if k.get("kty") == "EC" and k.get("crv") == "P-256" and typ in k.get("typ", [typ]):
            public = {n: k[n] for n in ("kty", "crv", "x", "y")}
            keys.append(ECKey.import_key({**public, "kid": k.get("kid") or ECKey.import_key(public).thumbprint()}))
    return KeySet(keys)


def check(token: str, jwks: dict, typ: str) -> tuple[dict, bytes]:
    obj = jws.deserialize_compact(token, keyset(jwks, typ), algorithms=["ES256"])  # any other alg is refused
    headers = obj.headers()
    if headers.get("typ") != typ:
        raise ValueError(f"typ is {headers.get('typ')!r}, expected {typ!r}")
    return headers, obj.payload


def verify_quote(quote: dict, keys: dict) -> str:
    token = quote.get("quote_jws")
    if not token:
        raise ValueError("the quote has no quote_jws")
    headers, payload = check(token, keys, "quote+jws")
    expected = rfc8785.dumps({k: v for k, v in quote.items() if k not in QUOTE_UNSIGNED})
    if payload != expected:
        raise ValueError("the quote differs from what was signed")
    return f"quote {quote.get('quote_id')} verifies: EUR {quote.get('total_net')} excl. VAT, kid {headers['kid']}"


def verify_receipt(order: dict, keys: dict) -> str:
    token = order.get("receipt_jws")
    if not token:
        raise ValueError(f"order {order.get('order_id')} has no receipt_jws (status {order.get('status')})")
    headers, payload = check(token, keys, "order-receipt+jws")
    receipt = json.loads(payload)
    diff = [f for f in RECEIPT_FIELDS if receipt.get(f) != order.get(f)]
    if diff or receipt.get("status") != "completed":
        raise ValueError(f"the order differs from its receipt: {', '.join(diff) or 'status'}")
    return f"receipt for order {order.get('order_id')} verifies: EUR {receipt['total_net']}, kid {headers['kid']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="a quote or order as a URL or a JSON file")
    ap.add_argument("--jwks", help="the JWKS URL or file (default: the source's origin, else localhost:8000)")
    ap.add_argument("--cookie", help="the va_session cookie value, to read a quote from the gateway's /v1 routes")
    args = ap.parse_args(argv)
    try:
        doc = fetch(args.source, args.cookie)
        if args.jwks:
            jwks_source = args.jwks
        elif args.source.startswith(("http://", "https://")):
            u = urlsplit(args.source)
            jwks_source = f"{u.scheme}://{u.netloc}/.well-known/jwks.json"
        else:
            jwks_source = "http://localhost:8000/.well-known/jwks.json"
        keys = fetch(jwks_source)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    doc = doc.get("quote") or doc.get("order") or doc
    try:
        print(verify_receipt(doc, keys) if "order_id" in doc and "lines" not in doc else verify_quote(doc, keys))
    except (JoseError, ValueError) as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
