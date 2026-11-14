"""Signed quotes with fixed prices (PLAN M6.2-M6.4): ES256 over RFC 8785 JSON, the JWKS and scripts/verify_quote.py."""

import base64
import importlib.util
import json
import stat
from datetime import datetime
from pathlib import Path

import pytest
import rfc8785
from app import signing
from app.settings import Settings
from app.stubs import quote_expiry
from joserfc import jws
from joserfc.jwk import ECKey, OctKey
from test_orders import MILK, quote_for

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("verify_quote", REPO / "scripts" / "verify_quote.py")
assert _spec and _spec.loader
verify_quote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_quote)


def jwks(c) -> dict:
    r = c.get("/.well-known/jwks.json")
    assert r.status_code == 200
    return r.json()


def new_quote(c, amount: float = 396) -> dict:
    offers = c.post("/v1/offers", json={**MILK, "amount": amount}).json()
    return c.post("/v1/quotes", json={"offer_id": offers["options"][0]["offer_id"]}).json()


def run_script(tmp_path: Path, doc: dict, keys: dict) -> int:
    (tmp_path / "doc.json").write_text(json.dumps(doc))
    (tmp_path / "jwks.json").write_text(json.dumps(keys))
    return verify_quote.main([str(tmp_path / "doc.json"), "--jwks", str(tmp_path / "jwks.json")])


# ---- M6.3 the JWS and the JWKS ------------------------------------------------------------------


def test_the_jwks_serves_two_public_p256_keys_named_by_thumbprint(chef):
    keys = jwks(chef)["keys"]
    assert len(keys) == 2 and len({k["kid"] for k in keys}) == 2
    for k in keys:
        assert (k["kty"], k["crv"], k["alg"], k["use"]) == ("EC", "P-256", "ES256", "sig")
        assert "d" not in k  # never the private part
        assert k["kid"] == ECKey.import_key({n: k[n] for n in ("kty", "crv", "x", "y")}).thumbprint()


def test_a_quote_verifies_against_the_jwks_and_a_changed_total_fails(chef, tmp_path):
    q = new_quote(chef)["quote"]
    token = jws.extract_compact(q["quote_jws"].encode())
    assert token.headers()["alg"] == "ES256" and token.headers()["typ"] == signing.TYP_QUOTE
    assert token.headers()["kid"] == jwks(chef)["keys"][0]["kid"]  # the gateway key, not the org admin key
    payload = token.payload
    assert payload == rfc8785.dumps({k: v for k, v in q.items() if k not in signing.QUOTE_UNSIGNED})
    assert '"total_net":"399.96"' in payload.decode()  # money stays a decimal string
    assert run_script(tmp_path, q, jwks(chef)) == 0

    assert run_script(tmp_path, {**q, "total_net": "39.96"}, jwks(chef)) == 1
    changed_line = {**q, "lines": [{**q["lines"][0], "qty": 1}]}
    assert run_script(tmp_path, changed_line, jwks(chef)) == 1


def test_confirming_keeps_the_quote_verifiable(chef, tmp_path):
    q = quote_for(chef)
    confirmed = chef.get(f"/v1/quotes/{q['quote_id']}").json()
    assert confirmed["confirmed"] is True and confirmed["quote_jws"] == q["quote"]["quote_jws"]
    assert run_script(tmp_path, confirmed, jwks(chef)) == 0
    assert run_script(tmp_path, {"quote": confirmed}, jwks(chef)) == 0  # a tool answer that holds the quote


def test_a_token_with_another_alg_is_rejected(chef, tmp_path):
    q = new_quote(chef)["quote"]
    payload = jws.extract_compact(q["quote_jws"].encode()).payload
    keys = jwks(chef)
    hs = jws.serialize_compact({"alg": "HS256", "typ": signing.TYP_QUOTE}, payload, OctKey.generate_key(256))
    with pytest.raises(signing.SignatureInvalid):
        signing.verify(hs, keys, signing.TYP_QUOTE)
    assert run_script(tmp_path, {**q, "quote_jws": hs}, keys) == 1

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    unsigned = f"{b64(json.dumps({'alg': 'none', 'typ': signing.TYP_QUOTE}).encode())}.{b64(payload)}."
    with pytest.raises(signing.SignatureInvalid):
        signing.verify(unsigned, keys, signing.TYP_QUOTE)
    assert run_script(tmp_path, {**q, "quote_jws": unsigned}, keys) == 1


def test_a_quote_signed_by_another_key_is_rejected(chef, tmp_path):
    q = new_quote(chef)["quote"]
    other = signing.Signer(ECKey.generate_key("P-256", private=True))
    forged = other.sign(signing.quote_document(chef.app.state.stubs.quotes[q["quote_id"]]), signing.TYP_QUOTE)
    assert run_script(tmp_path, {**q, "quote_jws": forged}, jwks(chef)) == 1


def test_a_basket_quote_is_signed_too(chef, tmp_path):
    b = chef.post("/v1/baskets/lines", json={**MILK, "basket_id": "new", "amount": 100}).json()
    res = chef.post("/v1/baskets/quote", json={"basket_id": b["basket"]["basket_id"]}).json()
    assert res["status"] == "ready_for_complete" and res["quote"]["quote_jws"]
    assert not any("not signed" in w for w in res["warnings"])
    assert run_script(tmp_path, res, jwks(chef)) == 0


# ---- M6.2 evidence ------------------------------------------------------------------------------


def test_each_quote_shows_the_snapshot_it_came_from(chef):
    q = new_quote(chef)
    ev = q["quote"]["evidence"]
    assert ev["api_time_now"] == "2026-11-14T01:16:59+0200" and ev["stub"] is True
    assert len(ev["response_sha256"]) == 2 and all(len(h) == 64 for h in ev["response_sha256"])  # /price, /availability
    assert not any("not signed" in w for w in q["warnings"])
    again = new_quote(chef, amount=500)["quote"]["evidence"]["response_sha256"]
    assert again == ev["response_sha256"]  # the same product and date: the same /price and /availability answers
    later = chef.post("/v1/offers", json={**MILK, "amount": 396, "need_date": "2026-11-17"}).json()
    other = chef.post("/v1/quotes", json={"offer_id": later["options"][0]["offer_id"]}).json()
    assert other["quote"]["evidence"]["response_sha256"][1] != ev["response_sha256"][1]  # another closingTime


# ---- M6.4 validity ------------------------------------------------------------------------------


def test_expires_at_is_the_earliest_of_ttl_cutoff_and_valid_to():
    issued = datetime.fromisoformat("2026-11-14T10:00:00+02:00")
    assert quote_expiry(issued, [("464306", "2026-11-16")]).isoformat() == "2026-11-14T10:15:00+02:00"
    late = issued.replace(day=15, hour=16, minute=50)  # ten minutes before Sunday's 17:00 cut-off
    assert quote_expiry(late, [("464306", "2026-11-16")]).isoformat() == "2026-11-15T17:00:00+02:00"
    dec31 = issued.replace(month=12, day=31, hour=23, minute=50)  # 464306 is a net price, valid to 2026-12-31
    assert quote_expiry(dec31, [("464306", "2027-01-04")]).isoformat() == "2027-01-01T00:00:00+02:00"


def test_an_expired_quote_can_be_neither_confirmed_nor_ordered(chef, settings):
    q = new_quote(chef)
    settings.as_of = "2026-11-14T10:16:00+02:00"
    c = chef.post(f"/v1/quotes/{q['quote_id']}/confirm").json()
    assert (c["status"], c["reason_code"]) == ("incomplete", "quote_expired")
    o = chef.post("/v1/orders", json={"quote_id": q["quote_id"]}).json()
    assert o["reason_code"] in ("confirmation_required", "quote_expired") and o["order_id"] is None


# ---- keys ---------------------------------------------------------------------------------------


def test_a_missing_key_is_generated_once_git_ignored_and_reused(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "data" / "gw.db")
    ring = signing.load(s)
    d = tmp_path / "data" / "keys"
    assert (d / ".gitignore").read_text().strip().endswith("*")
    for f in (signing.QUOTE_KEY_FILE, signing.ADMIN_KEY_FILE):
        assert stat.S_IMODE((d / f).stat().st_mode) == 0o600
    signing._load.cache_clear()
    again = signing.load(s)
    assert (again.quotes.kid, again.admin.kid) == (ring.quotes.kid, ring.admin.kid)


def test_keys_from_settings_win_over_files(tmp_path):
    quote_key, admin_key = (ECKey.generate_key("P-256", private=True) for _ in range(2))
    s = Settings(
        _env_file=None,
        db_path=tmp_path / "gw.db",
        signing_key=quote_key.as_pem(private=True).decode(),
        org_admin_key=json.dumps(admin_key.as_dict(private=True)),
    )
    ring = signing.load(s)
    assert (ring.quotes.kid, ring.admin.kid) == (quote_key.thumbprint(), admin_key.thumbprint())
    assert not (tmp_path / "keys").exists()
    with pytest.raises(ValueError):  # one key for both roles would let the gateway sign mandates
        signing.load(Settings(_env_file=None, signing_key=s.org_admin_key, org_admin_key=s.org_admin_key))
