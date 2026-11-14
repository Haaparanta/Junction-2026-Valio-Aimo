"""Valio Aimo client (PLAN M3.1, M3.2, M3.6): id validation, chunking, sequential calls, retries, cache, replay.

No test touches the network: live mode runs over httpx.MockTransport, replay over a tiny fixture set in tmp_path.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

import httpx
import pytest
from app.clients import valio
from app.clients.valio import (
    MAX_IDS_PER_CALL,
    ReplayUnavailable,
    ValioClient,
    ValioConfig,
    ValioConfigError,
    ValioRequestRejected,
    ValioUnavailable,
    validate_ids,
)

KEY = "test-key-not-real"


def avail_body(ids: list[str], time_now: str = "2026-11-14T10:00:00+0200") -> dict:
    return {
        "timeNow": time_now,
        "requestedDate": "2026-11-16T00:00:00+0200",
        "products": [
            {
                "productId": i,
                "closingTime": "2026-11-15T17:00:00+0200",
                "salesBlock": False,
                "logisticModel": "Stock",
                "scheduleLines": [
                    {"salesBlock": False, "availableAmount": 5.0, "availableDate": "2026-11-16", "salesUnit": "ST"}
                ],
            }
            for i in ids
        ],
    }


class FakeApi:
    """A MockTransport handler that records requests, tracks concurrency and can fail on demand."""

    def __init__(self, failures: list = (), status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.failures = list(failures)  # each: an int status, or an exception instance, consumed in order
        self.in_flight = 0
        self.max_in_flight = 0
        self.status = status
        self.bodies: list[bytes] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            if self.failures:
                f = self.failures.pop(0)
                if isinstance(f, Exception):
                    raise f
                return httpx.Response(f, headers={"retry-after": "3"} if f == 429 else {})
            if request.url.path.endswith("/ping"):
                body = b'{"status":"ok"}'
            else:
                ids = json.loads(request.content)["products"]
                body = json.dumps(avail_body(ids)).encode()
            self.bodies.append(body)
            return httpx.Response(self.status, content=body)
        finally:
            self.in_flight -= 1


def live_client(api: FakeApi, **kw) -> tuple[ValioClient, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    config = ValioConfig(mode="live", api_key=KEY, **kw)
    return ValioClient(config, transport=httpx.MockTransport(api), sleep=fake_sleep), sleeps


# ---- id validation (X-20) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("464306", "464306"),
        (464306, "464306"),
        ("460063 ", "460063"),  # trimmed: the API itself would answer error: true (A-07)
        (" 460063", "460063"),
        ("460000", "460000"),
        ("477545", "477545"),
        ("999999", "out_of_range"),
        ("477546", "out_of_range"),
        ("459999", "out_of_range"),
        ("000000", "out_of_range"),
        ("0460063", "not_six_digits"),
        ("460063.0", "not_six_digits"),
        ("abc", "not_six_digits"),
        ("", "not_six_digits"),
        ("４６００６３", "not_six_digits"),  # full-width digits
        ("4", "not_six_digits"),  # deposit material codes (X-19)
        ("147", "not_six_digits"),
        ("9708918", "not_six_digits"),
        (None, "not_a_string"),
        (True, "not_a_string"),
        (464306.0, "not_a_string"),
    ],
)
def test_check_product_id(raw, expected):
    got = valio.check_product_id(raw)
    assert (got if isinstance(got, str) else got.reason) == expected


def test_validate_ids_dedupes_in_first_seen_order():
    check = validate_ids(["464306", " 463038", "464306", "abc", "463038 ", 464306])
    assert check.valid == ["464306", "463038"]
    assert [r.raw for r in check.rejected] == ["abc"]


async def test_bad_ids_never_reach_the_api():
    api = FakeApi()
    client, _ = live_client(api)
    result = await client.price(["999999", "abc", "477546", "460063.0"], "2026-11-16")
    assert api.requests == []
    assert result.entries == {}
    assert {r.reason for r in result.rejected} == {"out_of_range", "not_six_digits"}


# ---- live calls -----------------------------------------------------------------------------


async def test_request_shape_header_and_timeout():
    api = FakeApi()
    client, _ = live_client(api)
    result = await client.availability([" 464306"], "2026-11-16")
    (req,) = api.requests
    assert req.method == "POST"
    assert str(req.url) == "https://junction26.valioaimo.fi/api/availability"
    assert req.headers["x-api-key"] == KEY
    assert json.loads(req.content) == {"customer": "123", "requestedDate": "2026-11-16", "products": ["464306"]}
    assert result.entries["464306"]["logisticModel"] == "Stock"
    assert result.time_now == "2026-11-14T10:00:00+0200"
    assert client._live._client().timeout.read == 5.0


async def test_at_most_1000_ids_per_call_and_sequential():
    api = FakeApi()
    client, _ = live_client(api)
    ids = [str(460000 + i) for i in range(2500)]
    first, second = await asyncio.gather(client.availability(ids, "2026-11-16"), client.price(ids[:10], "2026-11-16"))
    sizes = [len(json.loads(r.content)["products"]) for r in api.requests]
    assert sorted(sizes) == [10, 500, MAX_IDS_PER_CALL, MAX_IDS_PER_CALL]
    assert api.max_in_flight == 1  # never two calls at once, even from concurrent callers
    assert len(first.entries) == 2500 and len(first.evidence) == 3
    assert len(second.entries) == 10


async def test_retries_on_5xx_and_429_with_backoff():
    api = FakeApi(failures=[503, 429])
    client, sleeps = live_client(api)
    result = await client.availability(["464306"], "2026-11-16")
    assert len(api.requests) == 3
    assert sleeps == [0.5, 3.0]  # exponential backoff, then the Retry-After header
    assert "464306" in result.entries


async def test_timeouts_exhaust_retries():
    api = FakeApi(failures=[httpx.ReadTimeout("slow")] * 4)
    client, sleeps = live_client(api)
    with pytest.raises(ValioUnavailable) as err:
        await client.price(["464306"], "2026-11-16")
    assert err.value.attempts == 4 and err.value.last == "timeout"
    assert sleeps == [0.5, 1.0, 2.0]


async def test_422_is_not_retried_and_keeps_only_error_types(caplog):
    class Rejecting(FakeApi):
        async def __call__(self, request):
            self.requests.append(request)
            detail = [{"type": "too_long", "input": ["464306"] * 50}]
            return httpx.Response(422, json={"detail": detail})

    api = Rejecting()
    client, sleeps = live_client(api)
    with caplog.at_level(logging.DEBUG), pytest.raises(ValioRequestRejected) as err:
        await client.price(["464306"], "2026-11-16")
    assert len(api.requests) == 1 and sleeps == []
    assert err.value.error_types == ["too_long"]
    assert "464306" not in str(err.value)


async def test_key_never_appears_in_repr_errors_or_logs(caplog):
    config = ValioConfig(mode="live", api_key=KEY)
    assert KEY not in repr(config)
    api = FakeApi(failures=[500] * 4)
    client, _ = live_client(api)
    with caplog.at_level(logging.DEBUG), pytest.raises(ValioUnavailable) as err:
        await client.availability(["464306"], "2026-11-16")
    assert KEY not in str(err.value)
    assert KEY not in caplog.text


def test_live_mode_needs_a_key():
    with pytest.raises(ValioConfigError):
        ValioClient(ValioConfig(mode="live", api_key=None))


def test_config_from_env():
    config = ValioConfig.from_env(
        {"VALIO_MODE": "LIVE", "VALIO_AIMO_API_KEY": " k ", "VALIO_AIMO_API_BASE_URL": "http://x/api/"}
    )
    assert (config.mode, config.api_key, config.base_url) == ("live", "k", "http://x/api")
    assert ValioConfig.from_env({}).mode == "replay"
    with pytest.raises(ValioConfigError):
        ValioConfig.from_env({"VALIO_MODE": "record"})


# ---- cache and evidence (M3.6) --------------------------------------------------------------


async def test_evidence_hash_is_over_the_raw_body():
    api = FakeApi()
    client, _ = live_client(api)
    result = await client.availability(["464306", "463038"], "2026-11-16")
    (ev,) = result.evidence
    assert ev.sha256 == hashlib.sha256(api.bodies[0]).hexdigest()
    assert ev.source == "live" and ev.ids == ("464306", "463038") and ev.time_now == "2026-11-14T10:00:00+0200"
    assert result.entry_evidence == {"464306": ev.sha256, "463038": ev.sha256}
    assert result.evidence_for("463038") == ev


async def test_ttl_cache_keeps_the_hash_and_fetches_only_new_ids():
    clock = [0.0]
    api = FakeApi()
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    client = ValioClient(
        ValioConfig(mode="live", api_key=KEY, cache_ttl_s=60),
        transport=httpx.MockTransport(api),
        sleep=fake_sleep,
        monotonic=lambda: clock[0],
    )
    first = await client.availability(["464306", "463038"], "2026-11-16")
    clock[0] = 30
    second = await client.availability(["464306", "465244"], "2026-11-16")
    assert [json.loads(r.content)["products"] for r in api.requests] == [["464306", "463038"], ["465244"]]
    assert second.cached_ids == ["464306"]
    assert second.entry_evidence["464306"] == first.entry_evidence["464306"]
    assert len(second.evidence) == 2
    other_date = await client.availability(["464306"], "2026-11-20")
    assert other_date.cached_ids == []  # the key includes the requested date
    clock[0] = 100
    third = await client.availability(["464306"], "2026-11-16")
    assert third.cached_ids == [] and len(api.requests) == 4


# ---- replay (M3.2) --------------------------------------------------------------------------


def write_fixtures(root: Path) -> dict:
    """A tiny recording in the layout of scripts/record_fixtures.py."""
    files = []

    def put(set_name: str, req_date: str, endpoint: str, body: dict) -> None:
        rel = Path("raw") / set_name / req_date / f"{endpoint}-000.json"
        raw = json.dumps(body).encode()
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(raw)
        files.append(
            {
                "set": set_name,
                "endpoint": endpoint,
                "requested_date": req_date,
                "path": str(rel),
                "http_status": 200,
                "ids": [p["productId"] for p in body["products"]],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "time_now": body.get("timeNow"),
                "request": {"customer": "123", "requestedDate": req_date},
            }
        )

    put("named", "2026-11-16", "availability", avail_body(["464306"], "2026-11-14T20:20:16+0200"))
    put("named", "2026-11-16", "price", {"products": [{"productId": "464306", "catalogPrice": {"value": 1.01}}]})
    put("catalog", "2026-11-16", "availability", avail_body(["464306", "460056"], "2026-11-14T20:20:20+0200"))
    put("named", "2026-11-20", "availability", avail_body(["464306"], "2026-11-14T20:20:18+0200"))
    put("malformed", "2026-11-16", "price", {"products": [{"productId": "abc", "error": True}]})
    (root / "ping.json").write_bytes(b'{"status":"ok"}')
    files.insert(
        0,
        {
            "endpoint": "ping",
            "path": "ping.json",
            "http_status": 200,
            "sha256": hashlib.sha256(b'{"status":"ok"}').hexdigest(),
        },
    )
    manifest = {"recorded_started_at": "2026-11-14T18:20:15+00:00", "customer": "123", "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("replay mode must not open an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)


async def test_replay_serves_recorded_bodies_with_their_hashes(tmp_path, no_network):
    manifest = write_fixtures(tmp_path)
    client = ValioClient(ValioConfig(mode="replay", fixtures_dir=tmp_path))
    assert (await client.ping()).ok
    result = await client.availability(["464306", "460056", "abc"], "2026-11-16")
    named, catalog = manifest["files"][1], manifest["files"][3]
    assert result.entry_evidence == {"464306": named["sha256"], "460056": catalog["sha256"]}  # named set first
    ev = result.evidence_for("464306")
    assert ev.source == "replay" and ev.fixture_path == named["path"] and ev.recorded_date is None
    assert ev.time_now == "2026-11-14T20:20:16+0200"
    assert [r.raw for r in result.rejected] == ["abc"]  # malformed ids are never served, even when recorded
    assert result.time_now == "2026-11-14T20:20:20+0200"


async def test_replay_uses_the_date_recording_then_falls_back(tmp_path, no_network):
    manifest = write_fixtures(tmp_path)
    client = ValioClient(ValioConfig(mode="replay", fixtures_dir=tmp_path))
    later = await client.availability(["464306"], "2026-11-20")
    assert later.entry_evidence["464306"] == manifest["files"][4]["sha256"]
    other = await client.availability(["464306", "470000"], "2026-11-17")
    assert other.evidence_for("464306").recorded_date == "2026-11-16"
    assert other.missing == ["470000"]
    assert other.warnings == ["REPLAY_DATE_SUBSTITUTED", "REPLAY_NOT_RECORDED"]


async def test_replay_refuses_tampered_or_missing_fixtures(tmp_path, no_network):
    write_fixtures(tmp_path)
    path = tmp_path / "raw" / "named" / "2026-11-16" / "price-000.json"
    path.write_text(path.read_text().replace("1.01", "0.01"))
    client = ValioClient(ValioConfig(mode="replay", fixtures_dir=tmp_path))
    with pytest.raises(ReplayUnavailable, match="sha256"):
        await client.price(["464306"], "2026-11-16")
    empty = ValioClient(ValioConfig(mode="replay", fixtures_dir=tmp_path / "nothing"))
    with pytest.raises(ReplayUnavailable, match="manifest"):
        await empty.availability(["464306"], "2026-11-16")


async def test_requested_date_must_be_a_plain_date(tmp_path):
    write_fixtures(tmp_path)
    client = ValioClient(ValioConfig(mode="replay", fixtures_dir=tmp_path))
    with pytest.raises(ValueError):
        await client.availability(["464306"], "16.11.2026")
