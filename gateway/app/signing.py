"""Signatures anyone can check (PLAN M6.3, M7.3, M8.5; tech-research §2).

* Compact JWS, ES256 only (P-256 keys, joserfc). Verification pins algorithms=["ES256"], so a token with any other
  `alg` (HS256, none, ...) is refused before its signature is looked at.
* The payload is RFC 8785 canonical JSON (rfc8785) of the signed document, so the same content always gives the same
  bytes. Money stays a decimal string; no floats are ever signed.
* `kid` is the key's RFC 7638 JWK thumbprint; `typ` names what is signed (quote, receipt, mandate).
* Two keys: the gateway key signs quotes and order receipts; the organisation admin key signs the mandates. Both
  public keys are served at /.well-known/jwks.json.

Keys come from the settings (a PEM or a private JWK in SIGNING_KEY / ORG_ADMIN_KEY) or from files in
signing_key_dir; in development a missing key is generated there on first start (the folder gets its own .gitignore)
and only its kid is logged.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import rfc8785
from joserfc import jws
from joserfc.errors import JoseError
from joserfc.jwk import ECKey, KeySet
from pydantic import BaseModel

from .settings import REPO_ROOT, Settings, get_settings

log = logging.getLogger(__name__)

ALG = "ES256"
ALGORITHMS = [ALG]  # pinned on every verify
TYP_QUOTE = "quote+jws"
TYP_RECEIPT = "order-receipt+jws"
TYP_MANDATE = "mandate+jws"
QUOTE_KEY_FILE = "gateway-signing.jwk.json"
ADMIN_KEY_FILE = "org-admin.jwk.json"
# A quote's confirmation state changes after it is issued (the buyer confirms it); everything else is fixed and
# signed. The same fields are left out of the hash an approval records (orders.quote_sha).
QUOTE_UNSIGNED = {"quote_jws", "status", "confirmed", "confirmed_at"}


class SignatureInvalid(Exception):
    """The token does not verify: wrong algorithm, unknown key, bad signature, or a payload other than expected."""


def canonical(doc: Any) -> bytes:
    """RFC 8785 canonical JSON of a dict, list or pydantic model (dumped in JSON mode first)."""
    if isinstance(doc, BaseModel):
        doc = doc.model_dump(mode="json")
    return rfc8785.dumps(doc)


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def quote_document(quote: BaseModel) -> dict:
    """What a quote's JWS covers: the quote without its jws field and its confirmation state."""
    return quote.model_dump(mode="json", exclude=QUOTE_UNSIGNED)


@dataclass(frozen=True)
class Signer:
    key: ECKey

    @property
    def kid(self) -> str:
        return self.key.thumbprint()

    def public_jwk(self) -> dict:
        return {**self.key.as_dict(private=False), "kid": self.kid, "use": "sig", "alg": ALG}

    def sign(self, doc: Any, typ: str) -> str:
        return jws.serialize_compact({"alg": ALG, "kid": self.kid, "typ": typ}, canonical(doc), self.key, ALGORITHMS)


@dataclass(frozen=True)
class Keyring:
    quotes: Signer  # quotes and order receipts
    admin: Signer  # the buyer organisation's admin: mandates

    def jwks(self) -> dict:
        return {"keys": [self.quotes.public_jwk(), self.admin.public_jwk()]}

    def public_keyset(self) -> KeySet:
        return keyset(self.jwks())


def keyset(jwks: dict) -> KeySet:
    """Public keys only: a private member in a JWKS is never used to verify."""
    keys = []
    for k in jwks.get("keys", []):
        if not isinstance(k, dict) or k.get("kty") != "EC" or k.get("crv") != "P-256":
            continue
        public = {n: k[n] for n in ("kty", "crv", "x", "y") if n in k}
        keys.append(ECKey.import_key({**public, "kid": k.get("kid") or ECKey.import_key(public).thumbprint()}))
    return KeySet(keys)


def verify(token: str, keys: KeySet | dict, typ: str, expected: Any = None) -> dict:
    """The verified payload of `token`. Raises SignatureInvalid on any other algorithm, an unknown kid, a bad
    signature, another `typ`, or (with `expected`) a payload that is not exactly canonical(expected)."""
    ks = keys if isinstance(keys, KeySet) else keyset(keys)
    try:
        obj = jws.deserialize_compact(token, ks, algorithms=ALGORITHMS)
    except (JoseError, ValueError, TypeError, KeyError) as e:
        raise SignatureInvalid(f"{type(e).__name__}: {e}") from None
    headers = obj.headers()
    if headers.get("alg") != ALG or headers.get("typ") != typ:
        raise SignatureInvalid(f"unexpected header {headers.get('alg')}/{headers.get('typ')}")
    if expected is not None and obj.payload != canonical(expected):
        raise SignatureInvalid("the signed content differs from the document")
    try:
        return json.loads(obj.payload)
    except ValueError as e:
        raise SignatureInvalid("payload is not JSON") from e


# ---- keys ----------------------------------------------------------------------------------------


def _import(value: str) -> ECKey:
    value = value.strip()
    key = ECKey.import_key(json.loads(value) if value.startswith("{") else value)
    if key.as_dict(private=False).get("crv") != "P-256" or not key.is_private:
        raise ValueError("a signing key must be a private P-256 key")
    return key


def _from_file_or_new(path: Path, label: str) -> ECKey:
    """Read the key at `path`, or create it there (development). Two processes starting at once agree on one key."""
    if path.is_file():
        return _import(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = path.parent / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# Signing keys: never commit.\n*\n", encoding="utf-8")
    key = ECKey.generate_key("P-256", private=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process won the race: use its key
        return _import(path.read_text(encoding="utf-8"))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(key.as_dict(private=True)))
    log.info("generated the %s signing key, kid %s", label, key.thumbprint())
    return key


def key_dir(settings: Settings) -> Path:
    if settings.signing_key_dir is not None:
        return settings.signing_key_dir
    db = Path(settings.db_path)
    return db.parent / "keys" if str(settings.db_path) != ":memory:" else REPO_ROOT / "data" / "keys"


@lru_cache(maxsize=16)
def _load(quote_value: str | None, admin_value: str | None, directory: str) -> Keyring:
    d = Path(directory)
    quotes = _import(quote_value) if quote_value else _from_file_or_new(d / QUOTE_KEY_FILE, "gateway")
    admin = _import(admin_value) if admin_value else _from_file_or_new(d / ADMIN_KEY_FILE, "org admin")
    if quotes.thumbprint() == admin.thumbprint():
        raise ValueError("the gateway key and the org admin key must differ")
    ring = Keyring(Signer(quotes), Signer(admin))
    log.info("signing keys: gateway kid %s, org admin kid %s", ring.quotes.kid, ring.admin.kid)
    return ring


def load(settings: Settings) -> Keyring:
    return _load(settings.signing_key, settings.org_admin_key, str(key_dir(settings)))


_active: Keyring | None = None


def configure(settings: Settings) -> Keyring:
    """Make the keys of these settings the process's keys (create_app calls this)."""
    global _active
    _active = load(settings)
    return _active


def keys() -> Keyring:
    """The process's keys: the configured ones, else those of the default settings."""
    return _active if _active is not None else configure(get_settings())
