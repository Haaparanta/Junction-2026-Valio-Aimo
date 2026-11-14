"""Valio Aimo mock API client: /ping, /price and /availability, live or replayed (PLAN M3.1, M3.2, M3.6).

Hygiene rules from docs/data-and-api-findings.md (A-00, A-07, A-14, A-15, G-10):
* ids are validated before any call: 6 ASCII digits in 460000-477545, trimmed and deduplicated. The API matches ids
  verbatim and answers unknown ones with HTTP 200 and a look-alike entry, so a bad id must never reach it (X-20);
* at most 1,000 ids per call, calls strictly sequential (one lock per client), 5 s timeout, backoff on 429 and 5xx;
* a TTL cache keyed by (endpoint, customer, requested date, product id), since the API sends `cache-control: no-store`;
* the key goes only into the `X-API-Key` header. It is never logged, never part of a repr or an error message.

Every raw response body is hashed (SHA-256) and the hash travels with each parsed entry as `Evidence`, so quotes and
audit rows can cite exactly which bytes a price or a cut-off came from. Cached and replayed entries keep the hash of the
response that first produced them.

`VALIO_MODE=replay` (the default) serves the fixtures recorded by scripts/record_fixtures.py from data/fixtures
(manifest.json plus raw bodies, each checked against its recorded hash), so the demo runs with the network unplugged.
`VALIO_MODE=live` calls the API.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://junction26.valioaimo.fi/api"
DEFAULT_CUSTOMER = "123"
MIN_PRODUCT_ID = 460000
MAX_PRODUCT_ID = 477545  # the 17,546 catalogue ids fill this range with no gaps (A-07)
MAX_IDS_PER_CALL = 1000  # 1,001 ids give HTTP 422 too_long (A-14)
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_CACHE_TTL_S = 300.0
DEFAULT_MAX_RETRIES = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# The snapshot is frozen across requested dates (A-01), so replay may answer another date from the main recording.
REPLAY_FALLBACK_DATE = "2026-11-16"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURES_DIR = _REPO_ROOT / "data" / "fixtures"

_ID_RE = re.compile(r"[0-9]{6}")  # ASCII only: str.isdigit() would accept full-width digits

Endpoint = Literal["ping", "price", "availability"]
Mode = Literal["live", "replay"]


# ---- errors ---------------------------------------------------------------------------------


class ValioError(Exception):
    """Base class. Messages never contain the API key or a raw response body."""


class ValioConfigError(ValioError):
    """The client cannot run as configured, e.g. live mode without a key."""


class ValioUnavailable(ValioError):
    """The API did not answer usefully after the retries (timeouts, 429 or 5xx)."""

    def __init__(self, endpoint: str, attempts: int, last: str) -> None:
        super().__init__(f"Valio Aimo /{endpoint} unavailable after {attempts} attempts ({last})")
        self.endpoint = endpoint
        self.attempts = attempts
        self.last = last


class ValioRequestRejected(ValioError):
    """The API rejected the request (4xx other than 429). Only the error types are kept: a 422 body echoes every id."""

    def __init__(self, endpoint: str, status: int, error_types: list[str]) -> None:
        super().__init__(f"Valio Aimo /{endpoint} rejected the request: HTTP {status} {error_types}")
        self.endpoint = endpoint
        self.status = status
        self.error_types = error_types


class ReplayUnavailable(ValioError):
    """Replay mode without a usable fixture set, or a fixture whose bytes no longer match the manifest hash."""


# ---- ids ------------------------------------------------------------------------------------


class RejectedId(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str
    reason: Literal["not_a_string", "not_six_digits", "out_of_range"]


class IdCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: list[str]
    rejected: list[RejectedId]


def check_product_id(raw: object) -> str | RejectedId:
    """The normalised id, or why it is rejected. Ints are accepted; surrounding whitespace is trimmed."""
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        return RejectedId(raw=repr(raw), reason="not_a_string")
    text = str(raw).strip()
    if not _ID_RE.fullmatch(text):
        return RejectedId(raw=str(raw), reason="not_six_digits")
    if not MIN_PRODUCT_ID <= int(text) <= MAX_PRODUCT_ID:
        return RejectedId(raw=str(raw), reason="out_of_range")
    return text


def is_valid_product_id(raw: object) -> bool:
    return isinstance(check_product_id(raw), str)


def validate_ids(ids: Iterable[object]) -> IdCheck:
    """Trim, validate and deduplicate ids, keeping first-seen order (X-20)."""
    valid: list[str] = []
    seen: set[str] = set()
    rejected: list[RejectedId] = []
    for raw in ids:
        checked = check_product_id(raw)
        if isinstance(checked, RejectedId):
            rejected.append(checked)
        elif checked not in seen:
            seen.add(checked)
            valid.append(checked)
    return IdCheck(valid=valid, rejected=rejected)


def chunked(ids: list[str], size: int = MAX_IDS_PER_CALL) -> list[list[str]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


# ---- results --------------------------------------------------------------------------------


class Evidence(BaseModel):
    """Which raw response an entry came from. `sha256` is over the exact response body bytes (M3.6)."""

    model_config = ConfigDict(frozen=True)

    endpoint: Endpoint
    sha256: str
    http_status: int
    source: Literal["live", "replay"]
    requested_date: str | None = None
    customer: str | None = None
    ids: tuple[str, ...] = ()
    time_now: str | None = None  # the server clock of /availability, as returned
    fetched_at: str  # when we received it (live) or recorded it (replay), ISO 8601 UTC
    fixture_path: str | None = None  # replay: path relative to the fixtures directory
    recorded_date: str | None = None  # replay: the requested date of the recording, when it differs


class ApiResult(BaseModel):
    """Parsed entries of one logical /price or /availability request, with their evidence."""

    model_config = ConfigDict(frozen=True)

    endpoint: Literal["price", "availability"]
    customer: str
    requested_date: str
    entries: dict[str, dict[str, Any]]  # product id -> raw entry, exactly as the API sent it
    entry_evidence: dict[str, str]  # product id -> sha256 of the response it came from
    evidence: list[Evidence]  # every distinct response used, in first-use order
    rejected: list[RejectedId] = []
    missing: list[str] = []  # valid ids the response (or the recording) did not contain
    time_now: str | None = None
    cached_ids: list[str] = []  # ids answered from the TTL cache
    warnings: list[str] = []

    def entry(self, product_id: str) -> dict[str, Any] | None:
        return self.entries.get(product_id)

    def evidence_for(self, product_id: str) -> Evidence | None:
        digest = self.entry_evidence.get(product_id)
        return next((e for e in self.evidence if e.sha256 == digest), None)


class PingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    body: dict[str, Any]
    evidence: Evidence


# ---- configuration --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValioConfig:
    mode: Mode = "replay"
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = field(default=None, repr=False)
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR
    customer: str = DEFAULT_CUSTOMER
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES  # retries after the first attempt
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0
    cache_ttl_s: float = DEFAULT_CACHE_TTL_S

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ValioConfig:
        """VALIO_MODE (live or replay, default replay), VALIO_AIMO_API_KEY, VALIO_AIMO_API_BASE_URL,
        VALIO_FIXTURES_DIR, VALIO_CUSTOMER and VALIO_CACHE_TTL_S."""
        env = os.environ if environ is None else environ
        mode = (env.get("VALIO_MODE") or "replay").strip().lower()
        if mode not in ("live", "replay"):
            raise ValioConfigError(f"VALIO_MODE must be live or replay, not {mode!r}")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            base_url=(env.get("VALIO_AIMO_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            api_key=(env.get("VALIO_AIMO_API_KEY") or "").strip() or None,
            fixtures_dir=Path(env.get("VALIO_FIXTURES_DIR") or DEFAULT_FIXTURES_DIR),
            customer=env.get("VALIO_CUSTOMER") or DEFAULT_CUSTOMER,
            cache_ttl_s=float(env.get("VALIO_CACHE_TTL_S") or DEFAULT_CACHE_TTL_S),
        )


# ---- backends: one raw call each ------------------------------------------------------------


@dataclass(frozen=True)
class _Raw:
    """One raw response: body bytes, already hashed, plus where it came from."""

    status: int
    body: bytes
    evidence: Evidence


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _error_types(body: bytes) -> list[str]:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return []
    if isinstance(detail, list):
        return sorted({str(d.get("type")) for d in detail if isinstance(d, dict) and d.get("type")})
    return []


class LiveBackend:
    """httpx against the real API, with timeout, retries and backoff. Not concurrency-safe on its own: the client
    serialises calls."""

    def __init__(
        self,
        config: ValioConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not config.api_key:
            raise ValioConfigError("live mode needs VALIO_AIMO_API_KEY (use proxy-injected in the cloud sandbox)")
        self._config = config
        self._transport = transport
        self._sleep = sleep
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._config.base_url,
                timeout=httpx.Timeout(self._config.timeout_s),
                headers={"X-API-Key": self._config.api_key or "", "Accept": "application/json"},
                transport=self._transport,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after", "")
            if retry_after.strip().isdigit():
                return min(float(retry_after), self._config.backoff_max_s)
        return min(self._config.backoff_base_s * (2**attempt), self._config.backoff_max_s)

    async def call(self, endpoint: Endpoint, body: dict[str, Any] | None) -> _Raw:
        attempts = self._config.max_retries + 1
        last = ""
        for attempt in range(attempts):
            response: httpx.Response | None = None
            started = time.monotonic()
            try:
                if endpoint == "ping":
                    response = await self._client().get("/ping")
                else:
                    response = await self._client().post(f"/{endpoint}", json=body)
            except httpx.TimeoutException:
                last = "timeout"
            except httpx.TransportError as e:
                last = type(e).__name__
            else:
                elapsed = time.monotonic() - started
                if response.status_code in RETRY_STATUSES:
                    last = f"HTTP {response.status_code}"
                else:
                    raw = response.content
                    digest = _sha256(raw)
                    log.info(
                        "valio /%s: HTTP %s, %d ids, %d bytes, %.2f s, sha256 %s",
                        endpoint,
                        response.status_code,
                        len((body or {}).get("products", [])),
                        len(raw),
                        elapsed,
                        digest[:12],
                    )
                    if response.status_code != 200:
                        raise ValioRequestRejected(endpoint, response.status_code, _error_types(raw))
                    evidence = Evidence(
                        endpoint=endpoint,
                        sha256=digest,
                        http_status=response.status_code,
                        source="live",
                        requested_date=(body or {}).get("requestedDate"),
                        customer=(body or {}).get("customer"),
                        ids=tuple((body or {}).get("products", [])),
                        fetched_at=_now_utc(),
                    )
                    return _Raw(status=response.status_code, body=raw, evidence=evidence)
            if attempt + 1 < attempts:
                delay = self._delay(attempt, response)
                log.warning("valio /%s: %s, retry %d in %.1f s", endpoint, last, attempt + 1, delay)
                await self._sleep(delay)
        raise ValioUnavailable(endpoint, attempts, last)


class ReplayBackend:
    """Serves data/fixtures (scripts/record_fixtures.py): manifest.json lists every raw body with its sha256 and ids.

    Lookup is per id: the named demo set first, then the full-catalogue snapshot. An id not recorded for the requested
    date is answered from the REPLAY_FALLBACK_DATE recording (the snapshot ignores the date, A-01), and the evidence
    says so in `recorded_date`. Bodies are read lazily and checked against the manifest hash.
    """

    _SET_ORDER = {"named": 0, "catalog": 1}

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = Path(fixtures_dir)
        self._manifest: dict[str, Any] | None = None
        # (endpoint, requested_date) -> id -> manifest file record
        self._index: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self._bodies: dict[str, dict[str, Any]] = {}  # fixture path -> parsed body
        self._entries: dict[str, dict[str, dict[str, Any]]] = {}  # fixture path -> id -> entry

    def _load(self) -> dict[str, Any]:
        if self._manifest is not None:
            return self._manifest
        path = self._dir / "manifest.json"
        if not path.is_file():
            raise ReplayUnavailable(f"no fixture manifest at {path}; run scripts/record_fixtures.py or use live mode")
        manifest = json.loads(path.read_text())
        files = [
            f
            for f in manifest.get("files", [])
            if f.get("endpoint") in ("price", "availability")
            and f.get("http_status") == 200
            and f.get("set") in self._SET_ORDER
        ]
        files.sort(key=lambda f: self._SET_ORDER[f["set"]])
        for f in files:
            by_id = self._index.setdefault((f["endpoint"], f["requested_date"]), {})
            for pid in f.get("ids", []):
                by_id.setdefault(pid, f)
        self._manifest = manifest
        return manifest

    def _read(self, record: dict[str, Any]) -> dict[str, Any]:
        rel = record["path"]
        if rel not in self._bodies:
            raw = (self._dir / rel).read_bytes()
            if _sha256(raw) != record["sha256"]:
                raise ReplayUnavailable(f"fixture {rel} does not match its manifest sha256")
            self._bodies[rel] = json.loads(raw)
            self._entries[rel] = {
                str(e.get("productId")): e for e in self._bodies[rel].get("products", []) if isinstance(e, dict)
            }
        return self._bodies[rel]

    def _evidence(self, record: dict[str, Any], requested_date: str) -> Evidence:
        manifest = self._load()
        return Evidence(
            endpoint=record["endpoint"],
            sha256=record["sha256"],
            http_status=record.get("http_status", 200),
            source="replay",
            requested_date=requested_date,
            customer=(record.get("request") or {}).get("customer", manifest.get("customer")),
            ids=tuple(record.get("ids", [])),
            time_now=record.get("time_now"),
            fetched_at=manifest.get("recorded_started_at") or "",
            fixture_path=record["path"],
            recorded_date=record["requested_date"] if record["requested_date"] != requested_date else None,
        )

    def ping(self) -> _Raw:
        self._load()
        path = self._dir / "ping.json"
        if not path.is_file():
            raise ReplayUnavailable(f"no recorded ping at {path}")
        raw = path.read_bytes()
        record = next((f for f in self._load().get("files", []) if f.get("endpoint") == "ping"), {})
        if record.get("sha256") and record["sha256"] != _sha256(raw):
            raise ReplayUnavailable("ping.json does not match its manifest sha256")
        evidence = Evidence(
            endpoint="ping",
            sha256=_sha256(raw),
            http_status=record.get("http_status", 200),
            source="replay",
            fetched_at=self._load().get("recorded_started_at") or "",
            fixture_path="ping.json",
        )
        return _Raw(status=evidence.http_status, body=raw, evidence=evidence)

    def lookup(
        self, endpoint: Literal["price", "availability"], requested_date: str, ids: list[str]
    ) -> tuple[dict[str, tuple[dict[str, Any], Evidence, str | None]], list[str]]:
        """id -> (entry, evidence, timeNow) for the recorded ids, plus the ids with no recording."""
        self._load()
        primary = self._index.get((endpoint, requested_date), {})
        fallback = self._index.get((endpoint, REPLAY_FALLBACK_DATE), {})
        found: dict[str, tuple[dict[str, Any], Evidence, str | None]] = {}
        missing: list[str] = []
        for pid in ids:
            record = primary.get(pid) or fallback.get(pid)
            if record is None:
                missing.append(pid)
                continue
            body = self._read(record)
            entry = self._entries[record["path"]].get(pid)
            if entry is None:
                missing.append(pid)
                continue
            found[pid] = (entry, self._evidence(record, requested_date), body.get("timeNow"))
        return found, missing


# ---- the client -----------------------------------------------------------------------------


@dataclass
class _Cached:
    entry: dict[str, Any]
    evidence: Evidence
    time_now: str | None
    stored_at: float


def _as_date_str(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    date.fromisoformat(text)  # raises ValueError on anything but YYYY-MM-DD
    return text


class ValioClient:
    """Async client. `price()` and `availability()` validate, chunk, cache and return an `ApiResult`."""

    def __init__(
        self,
        config: ValioConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or ValioConfig.from_env()
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._cache: dict[tuple[str, str, str, str], _Cached] = {}
        self._live: LiveBackend | None = None
        self._replay: ReplayBackend | None = None
        if self.config.mode == "live":
            self._live = LiveBackend(self.config, transport=transport, sleep=sleep)
        else:
            self._replay = ReplayBackend(self.config.fixtures_dir)

    @property
    def mode(self) -> Mode:
        return self.config.mode

    async def aclose(self) -> None:
        if self._live is not None:
            await self._live.aclose()

    async def __aenter__(self) -> ValioClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def clear_cache(self) -> None:
        self._cache.clear()

    async def ping(self) -> PingResult:
        async with self._lock:
            raw = self._replay.ping() if self._replay is not None else await self._live.call("ping", None)  # type: ignore[union-attr]
        try:
            body = json.loads(raw.body)
        except ValueError:
            body = {}
        return PingResult(ok=body.get("status") == "ok", body=body, evidence=raw.evidence)

    async def price(
        self, ids: Iterable[object], requested_date: date | str, *, customer: str | None = None
    ) -> ApiResult:
        return await self._fetch("price", ids, requested_date, customer)

    async def availability(
        self, ids: Iterable[object], requested_date: date | str, *, customer: str | None = None
    ) -> ApiResult:
        return await self._fetch("availability", ids, requested_date, customer)

    async def _fetch(
        self,
        endpoint: Literal["price", "availability"],
        ids: Iterable[object],
        requested_date: date | str,
        customer: str | None,
    ) -> ApiResult:
        req_date = _as_date_str(requested_date)
        cust = customer or self.config.customer
        check = validate_ids(ids)
        now = self._monotonic()
        got: dict[str, _Cached] = {}
        cached_ids: list[str] = []
        to_fetch: list[str] = []
        for pid in check.valid:
            hit = self._cache.get((endpoint, cust, req_date, pid))
            if hit is not None and now - hit.stored_at < self.config.cache_ttl_s:
                got[pid] = hit
                cached_ids.append(pid)
            else:
                to_fetch.append(pid)

        missing: list[str] = []
        warnings: list[str] = []
        if to_fetch:
            async with self._lock:  # strictly sequential calls, also across concurrent callers
                if self._replay is not None:
                    found, missing = self._replay.lookup(endpoint, req_date, to_fetch)
                    for pid, (entry, evidence, time_now) in found.items():
                        got[pid] = _Cached(entry, evidence, time_now, self._monotonic())
                else:
                    for part in chunked(to_fetch):
                        body = {"customer": cust, "requestedDate": req_date, "products": part}
                        raw = await self._live.call(endpoint, body)  # type: ignore[union-attr]
                        try:
                            parsed = json.loads(raw.body)
                        except ValueError as e:
                            raise ValioError(f"Valio Aimo /{endpoint} returned a body that is not JSON") from e
                        time_now = parsed.get("timeNow")
                        evidence = raw.evidence.model_copy(update={"time_now": time_now})
                        by_id = {str(e.get("productId")): e for e in parsed.get("products", []) if isinstance(e, dict)}
                        stored = self._monotonic()
                        for pid in part:
                            if pid in by_id:
                                got[pid] = _Cached(by_id[pid], evidence, time_now, stored)
                            else:
                                missing.append(pid)
            for pid in to_fetch:
                if pid in got:
                    self._cache[(endpoint, cust, req_date, pid)] = got[pid]
            if any(c.evidence.recorded_date for c in got.values()):
                warnings.append("REPLAY_DATE_SUBSTITUTED")
            if missing and self._replay is not None:
                warnings.append("REPLAY_NOT_RECORDED")

        entries: dict[str, dict[str, Any]] = {}
        entry_evidence: dict[str, str] = {}
        evidence: dict[str, Evidence] = {}
        time_now: str | None = None
        for pid in check.valid:
            hit = got.get(pid)
            if hit is None:
                continue
            entries[pid] = hit.entry
            entry_evidence[pid] = hit.evidence.sha256
            evidence.setdefault(hit.evidence.sha256, hit.evidence)
            if hit.time_now and (time_now is None or hit.time_now > time_now):
                time_now = hit.time_now
        return ApiResult(
            endpoint=endpoint,
            customer=cust,
            requested_date=req_date,
            entries=entries,
            entry_evidence=entry_evidence,
            evidence=list(evidence.values()),
            rejected=check.rejected,
            missing=missing,
            time_now=time_now,
            cached_ids=cached_ids,
            warnings=warnings,
        )


def client_from_env(environ: Mapping[str, str] | None = None) -> ValioClient:
    return ValioClient(ValioConfig.from_env(environ))
