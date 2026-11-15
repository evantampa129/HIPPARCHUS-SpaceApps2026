"""Public-hosting limits (hipparchus/guard.py). No network: a stub app stands in for the API."""

import asyncio
import os
import threading
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from hipparchus.guard import PublicGuard, RateLimiter, Settings, prune_cache, prune_manifests, validate_query


def _stub(delay: float = 0.0):
    inner = FastAPI()
    inner.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
    seen = {}

    @inner.get("/api/analyze")
    async def analyze(request: Request):
        seen["query"] = dict(request.query_params)
        await asyncio.sleep(delay)
        return {"ok": True}

    @inner.get("/api/observations")
    async def observations():
        return {"ok": True}

    @inner.get("/api/health")
    async def health():
        return {"status": "ok"}

    return inner, seen


def _guard(inner, **kw):
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return PublicGuard(inner, s)


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter({"analyze": (2, 60)}, clock=lambda: now[0])
    assert rl.check("a", "analyze") == 0
    assert rl.check("a", "analyze") == 0
    assert rl.check("a", "analyze") > 0       # third hit inside the window
    assert rl.check("b", "analyze") == 0      # other clients are independent
    now[0] = 61
    assert rl.check("a", "analyze") == 0      # window has slid


def test_validation_rejects_bad_input():
    for q in ["ra=nan&dec=0", "ra=inf&dec=0", "ra=360&dec=0", "ra=10&dec=91", "ra=abc&dec=0",
              "dec=0", "ra=1&dec=1&ra=2", "ra=1&dec=1&evil=1"]:
        assert validate_query("search", q, 60)[0], q
    assert validate_query("analyze", "ra=1&dec=1&detector=SPHEREx-D9", 60)[0]
    assert validate_query("analyze", "ra=1&dec=1&detector=SPHEREx-D1&limit=500", 60)[0]
    assert validate_query("search", "ra=76.956&dec=30.401", 60) == (None, "ra=76.956&dec=30.401")


def test_epoch_cap_is_added_when_missing():
    inner, seen = _stub()
    c = TestClient(_guard(inner, max_epochs=40))
    r = c.get("/api/analyze", params={"ra": 76.956, "dec": 30.401, "detector": "SPHEREx-D1"})
    assert r.status_code == 200
    assert seen["query"]["limit"] == "40"
    assert c.get("/api/analyze", params={"ra": "nan", "dec": 0, "detector": "SPHEREx-D1"}).status_code == 422


def test_rate_limit_returns_429_with_retry_after():
    inner, _ = _stub()
    c = TestClient(_guard(inner, rates={"analyze": (1, 3600), "search": (2, 600), "other": (100, 60)}))
    p = {"ra": 10, "dec": 10}
    assert c.get("/api/observations", params=p).status_code == 200
    assert c.get("/api/observations", params=p).status_code == 200
    r = c.get("/api/observations", params=p)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert c.get("/api/health").status_code == 200   # light routes have their own budget


def test_forwarded_for_uses_proxy_added_hop():
    g = _guard(_stub()[0], trusted_proxy_hops=1)
    scope = {"headers": [(b"x-forwarded-for", b"1.1.1.1, 9.9.9.9")], "client": ("10.0.0.1", 1)}
    assert g.client_ip(scope) == "9.9.9.9"     # the left entry could be forged by the client
    g0 = _guard(_stub()[0], trusted_proxy_hops=0)
    assert g0.client_ip(scope) == "10.0.0.1"


def test_read_only_and_cors_and_query_length():
    inner, _ = _stub()
    c = TestClient(_guard(inner, cors_origins=("https://ok.example",)))
    assert c.post("/api/analyze").status_code == 405
    assert c.get("/api/health?" + "x" * 1000).status_code == 414
    bad = c.get("/api/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    assert bad.headers["x-content-type-options"] == "nosniff"
    ok = c.get("/api/health", headers={"origin": "https://ok.example"})
    assert ok.headers.get("access-control-allow-origin")


def _run(coro):
    return asyncio.run(coro)


def test_concurrency_cap_and_timeout():
    inner, _ = _stub(delay=0.5)
    g = _guard(inner, max_analyses=1, analyze_timeout_s=0.2,
               rates={"analyze": (100, 60), "search": (100, 60), "other": (100, 60)})
    p = {"ra": 1, "dec": 1, "detector": "SPHEREx-D1"}

    async def go():
        t1 = httpx.ASGITransport(app=g, client=("1.1.1.1", 1))
        t2 = httpx.ASGITransport(app=g, client=("2.2.2.2", 1))
        async with httpx.AsyncClient(transport=t1, base_url="http://t") as a, \
                   httpx.AsyncClient(transport=t2, base_url="http://t") as b:
            first = asyncio.create_task(a.get("/api/analyze", params=p))
            await asyncio.sleep(0.05)
            busy = await b.get("/api/analyze", params=p)          # global cap reached
            same = await a.get("/api/analyze", params=p)          # same client, already running
            slow = await first                                    # exceeds the 0.2 s limit
            await asyncio.sleep(0.6)                              # background work finishes
            after = await b.get("/api/analyze", params=p)
            return busy.status_code, same.status_code, slow.status_code, after.status_code, g.active

    busy, same, slow, after, active = _run(go())
    assert (busy, same, slow) == (503, 429, 504)
    assert after == 504 or after == 200
    assert active == {"analyze": 0, "search": 0}


def test_results_in_memory_are_capped():
    results = {str(i): i for i in range(20)}
    g = PublicGuard(_stub()[0], Settings(), results=results, results_lock=threading.Lock())
    g.s.max_results = 5
    g._trim_results()
    assert list(results) == ["15", "16", "17", "18", "19"]


def test_cache_eviction_removes_oldest(tmp_path):
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "keep.fits").write_bytes(b"x" * 500)
    for i in range(5):
        f = tmp_path / f"c{i}.fits"
        f.write_bytes(b"x" * 100)
        (tmp_path / f"c{i}.json").write_text("{}")
        t = time.time() - 1000 + i
        os.utime(f, (t, t))
    removed = prune_cache(tmp_path, 300)
    left = sorted(p.name for p in tmp_path.glob("*.fits"))
    assert removed == 3 and left == ["c3.fits", "c4.fits"]
    assert not (tmp_path / "c0.json").exists()
    assert (tmp_path / "calibration" / "keep.fits").exists()


def test_manifest_pruning_keeps_presets(tmp_path):
    for i in range(6):
        p = tmp_path / f"obs_{i}.json"
        p.write_text("{}")
        os.utime(p, (i, i))
    assert prune_manifests(tmp_path, 3, {"obs_0.json"}) == 3
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["obs_0.json", "obs_4.json", "obs_5.json"]
