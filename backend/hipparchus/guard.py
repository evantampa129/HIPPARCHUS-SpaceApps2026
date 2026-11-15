"""Limits for running the demo on a public, no-login host.

Off by default: serve.py only adds this when HIPPARCHUS_PUBLIC=1, so local use
and the tests behave exactly as before. On a free host the danger is not data
leaks (everything here is public SPHEREx data and every route is a GET) but one
visitor, or a bot, using up the CPU, the disk or our share of IRSA. So:

- per-IP sliding-window rate limits, stricter for the slow routes;
- a global cap on analyses / archive searches running at once (no queue: a
  full server answers 503 at once instead of piling up threads);
- a time limit per slow request; the work keeps running and its result is
  cached, so retrying later is instant;
- strict checks of the query parameters before anything reaches the archive,
  and a cap on how many epochs one analysis may download;
- a size cap on the cutout cache with least-recently-used eviction, and a cap
  on finished analyses kept in memory;
- GET/HEAD only, and cross-origin reads only from listed origins.

It is plain ASGI (not BaseHTTPMiddleware) so a timed-out request can answer
504 while the real work finishes in the background and still holds its slot.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

SLOW_ROUTES = {"/api/analyze": "analyze", "/api/observations": "search"}
DETECTOR_RE = re.compile(r"^SPHEREx-D[1-6]$")
ALLOWED_PARAMS = {"analyze": {"ra", "dec", "detector", "limit"}, "search": {"ra", "dec"}}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _rate(spec: str, default: tuple[int, int]) -> tuple[int, int]:
    # "12/3600" = at most 12 requests in any 3600 s window.
    try:
        n, w = spec.split("/")
        return max(1, int(n)), max(1, int(w))
    except (ValueError, AttributeError):
        return default


@dataclass
class Settings:
    rates: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "analyze": (12, 3600), "search": (30, 600), "other": (600, 60)})
    max_analyses: int = 2          # free CPU Spaces have 2 vCPU / 16 GB
    max_searches: int = 4
    analyze_timeout_s: float = 420.0
    search_timeout_s: float = 240.0
    max_epochs: int = 60           # about one detector's full SPHEREx history at most positions
    cache_max_bytes: int = 3 * 1024**3
    max_manifests: int = 500
    max_results: int = 12          # finished analyses kept in memory for their images
    max_query_len: int = 256
    trusted_proxy_hops: int = 1    # 0: ignore X-Forwarded-For
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        s.rates = {
            "analyze": _rate(os.environ.get("HIPPARCHUS_RATE_ANALYZE", ""), s.rates["analyze"]),
            "search": _rate(os.environ.get("HIPPARCHUS_RATE_SEARCH", ""), s.rates["search"]),
            "other": _rate(os.environ.get("HIPPARCHUS_RATE_OTHER", ""), s.rates["other"]),
        }
        s.max_analyses = max(1, _env_int("HIPPARCHUS_MAX_ANALYSES", s.max_analyses))
        s.max_searches = max(1, _env_int("HIPPARCHUS_MAX_SEARCHES", s.max_searches))
        s.analyze_timeout_s = _env_int("HIPPARCHUS_ANALYZE_TIMEOUT_S", int(s.analyze_timeout_s))
        s.search_timeout_s = _env_int("HIPPARCHUS_SEARCH_TIMEOUT_S", int(s.search_timeout_s))
        s.max_epochs = max(2, _env_int("HIPPARCHUS_MAX_EPOCHS", s.max_epochs))
        s.cache_max_bytes = _env_int("HIPPARCHUS_CACHE_MAX_MB", s.cache_max_bytes // 1024**2) * 1024**2
        s.max_manifests = _env_int("HIPPARCHUS_MAX_MANIFESTS", s.max_manifests)
        s.max_results = max(1, _env_int("HIPPARCHUS_MAX_RESULTS", s.max_results))
        s.trusted_proxy_hops = max(0, _env_int("HIPPARCHUS_TRUSTED_PROXY_HOPS", s.trusted_proxy_hops))
        s.cors_origins = tuple(o.strip() for o in os.environ.get("HIPPARCHUS_CORS_ORIGINS", "").split(",")
                               if o.strip())
        return s


class RateLimiter:
    """Sliding window per (client, bucket). In memory: one process, one replica."""

    def __init__(self, rates: dict[str, tuple[int, int]], clock=time.monotonic):
        self.rates = rates
        self.clock = clock
        self.hits: dict[tuple[str, str], deque] = {}

    def check(self, client: str, bucket: str) -> float:
        """Record a hit and return 0, or return the seconds to wait if over the limit."""
        n, window = self.rates[bucket]
        now = self.clock()
        q = self.hits.setdefault((client, bucket), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= n:
            return max(1.0, q[0] + window - now)
        q.append(now)
        if len(self.hits) > 20000:  # forget idle clients so the table cannot grow forever
            for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - self.rates[k[1]][1]]:
                del self.hits[k]
        return 0.0


def validate_query(kind: str, query: str, max_epochs: int) -> tuple[str | None, str]:
    """Check the parameters of a slow route. Returns (error, query to forward)."""
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=bool(query))
    except ValueError:
        return "Malformed query string.", query
    params: dict[str, str] = {}
    for k, v in pairs:
        if k not in ALLOWED_PARAMS[kind]:
            return f"Unknown parameter '{k}'.", query
        if k in params:
            return f"Parameter '{k}' given twice.", query
        params[k] = v
    for k in ("ra", "dec"):
        if k not in params:
            return f"Missing parameter '{k}'.", query
        try:
            x = float(params[k])
        except ValueError:
            return f"'{k}' must be a number in degrees.", query
        if not math.isfinite(x):
            return f"'{k}' must be a finite number.", query
        if k == "ra" and not 0 <= x < 360:
            return "'ra' must be in [0, 360) degrees.", query
        if k == "dec" and not -90 <= x <= 90:
            return "'dec' must be in [-90, 90] degrees.", query
    if kind == "analyze":
        if not DETECTOR_RE.match(params.get("detector", "")):
            return "'detector' must be one of SPHEREx-D1 ... SPHEREx-D6.", query
        if "limit" in params:
            try:
                lim = int(params["limit"])
            except ValueError:
                return "'limit' must be an integer.", query
            if not 2 <= lim <= max_epochs:
                return f"'limit' must be between 2 and {max_epochs} on this public server.", query
        else:
            # The page asks for every epoch; here that is capped so one request
            # cannot download thousands of cutouts at a deep-field position.
            params["limit"] = str(max_epochs)
    return None, urlencode(params)


def prune_cache(cache_dir: Path, max_bytes: int) -> int:
    """Delete least-recently-used cutouts (FITS + its JSON) until under 80 % of the cap.

    Only top-level cutout files are touched; calibration/ and sia/ stay.
    Returns the number of cutouts removed.
    """
    if max_bytes <= 0 or not cache_dir.is_dir():
        return 0
    items = []
    total = 0
    for p in cache_dir.glob("*.fits"):
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        items.append((max(st.st_atime, st.st_mtime), st.st_size, p))
        total += st.st_size
    if total <= max_bytes:
        return 0
    removed = 0
    for _, size, p in sorted(items):
        if total <= 0.8 * max_bytes:
            break
        for f in (p, p.with_suffix(".json")):
            try:
                f.unlink()
            except FileNotFoundError:
                pass
        total -= size
        removed += 1
    return removed


def prune_manifests(manifest_dir: Path, keep: int, protected: set[str]) -> int:
    """Keep at most `keep` saved archive listings; the preset targets' are never deleted."""
    if keep <= 0 or not manifest_dir.is_dir():
        return 0
    files = sorted((p for p in manifest_dir.glob("obs_*.json") if p.name not in protected),
                   key=lambda p: p.stat().st_mtime)
    extra = len(files) + len(protected) - keep
    for p in files[:max(0, extra)]:
        p.unlink(missing_ok=True)
    return max(0, extra)


class PublicGuard:
    def __init__(self, app, settings: Settings | None = None, *, cache_dir: Path | None = None,
                 manifest_dir: Path | None = None, protected_manifests: set[str] | None = None,
                 results: dict | None = None, results_lock=None, clock=time.monotonic):
        self.app = app
        self.s = settings or Settings.from_env()
        self.limiter = RateLimiter(self.s.rates, clock)
        self.cache_dir = cache_dir
        self.manifest_dir = manifest_dir
        self.protected = protected_manifests or set()
        self.results = results
        self.results_lock = results_lock
        self.active = {"analyze": 0, "search": 0}
        self.active_by_client: dict[str, int] = {}
        self.caps = {"analyze": self.s.max_analyses, "search": self.s.max_searches}
        self.timeouts = {"analyze": self.s.analyze_timeout_s, "search": self.s.search_timeout_s}

    # -- helpers ----------------------------------------------------------
    def client_ip(self, scope) -> str:
        if self.s.trusted_proxy_hops:
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-for":
                    hops = [h.strip() for h in value.decode("latin-1").split(",") if h.strip()]
                    # Take the address added by the outermost trusted proxy; anything
                    # further left was written by the client and could be forged.
                    if hops:
                        return hops[-min(self.s.trusted_proxy_hops, len(hops))]
        client = scope.get("client")
        return client[0] if client else "unknown"

    @staticmethod
    async def _send_json(send, status: int, detail: str, extra: list | None = None):
        body = json.dumps({"detail": detail}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                   (b"cache-control", b"no-store")] + (extra or [])
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _wrap_send(self, send, scope):
        origin = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"origin"), None)
        allowed = origin in self.s.cors_origins

        async def wrapped(msg):
            if msg["type"] == "http.response.start":
                headers = [(k, v) for k, v in msg.get("headers", [])
                           if allowed or not k.lower().startswith(b"access-control-")]
                headers += [(b"x-content-type-options", b"nosniff"),
                            (b"referrer-policy", b"no-referrer"),
                            (b"x-frame-options", b"SAMEORIGIN")]
                msg = {**msg, "headers": headers}
            await send(msg)
        return wrapped

    def _after_slow(self, kind: str, client: str):
        self.active[kind] -= 1
        self.active_by_client[client] -= 1
        if not self.active_by_client[client]:
            del self.active_by_client[client]
        self._trim_results()
        # Only delete cutouts when no analysis could be reading them right now.
        # This runs on the event loop thread, so no analysis can start meanwhile.
        if not self.active["analyze"] and self.cache_dir is not None:
            prune_cache(self.cache_dir, self.s.cache_max_bytes)
        if kind == "search" and self.manifest_dir is not None:
            prune_manifests(self.manifest_dir, self.s.max_manifests, self.protected)

    def _trim_results(self):
        if self.results is None:
            return
        lock = self.results_lock
        if lock:
            lock.acquire()
        try:
            while len(self.results) > self.s.max_results:
                self.results.pop(next(iter(self.results)))  # oldest first (insertion order)
        finally:
            if lock:
                lock.release()

    # -- ASGI -------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        send = self._wrap_send(send, scope)
        if scope["method"] not in ("GET", "HEAD"):
            return await self._send_json(send, 405, "This public demo is read-only.",
                                         [(b"allow", b"GET, HEAD")])
        if len(scope.get("query_string", b"")) > self.s.max_query_len:
            return await self._send_json(send, 414, "Query string too long.")

        path = scope["path"]
        kind = SLOW_ROUTES.get(path.rstrip("/"))
        client = self.client_ip(scope)
        wait = self.limiter.check(client, kind or "other")
        if wait:
            return await self._send_json(
                send, 429, f"Too many requests from your address; try again in {math.ceil(wait)} s.",
                [(b"retry-after", str(math.ceil(wait)).encode())])
        if kind is None:
            return await self.app(scope, receive, send)

        err, query = validate_query(kind, scope.get("query_string", b"").decode("latin-1"), self.s.max_epochs)
        if err:
            return await self._send_json(send, 422, err)
        if self.active_by_client.get(client):
            return await self._send_json(send, 429, "You already have a request running; wait for it to finish.",
                                         [(b"retry-after", b"30")])
        if self.active[kind] >= self.caps[kind]:
            return await self._send_json(
                send, 503, "The server is busy with other analyses; please try again in a minute.",
                [(b"retry-after", b"60")])

        scope = {**scope, "query_string": query.encode()}
        self.active[kind] += 1
        self.active_by_client[client] = self.active_by_client.get(client, 0) + 1
        state = {"started": False, "timed_out": False}

        async def guarded_send(msg):
            if state["timed_out"]:
                return  # the client already got a 504; drop the late answer
            if msg["type"] == "http.response.start":
                state["started"] = True
            await send(msg)

        task = asyncio.ensure_future(self.app(scope, receive, guarded_send))
        task.add_done_callback(lambda t: (self._after_slow(kind, client),
                                          t.cancelled() or t.exception()))
        done, _ = await asyncio.wait({task}, timeout=self.timeouts[kind])
        if task in done:
            return task.result()
        if not state["started"]:
            state["timed_out"] = True
            return await self._send_json(
                send, 504, "Still working (first downloads from IRSA can take several minutes). "
                           "The result is cached when ready: run the same request again shortly.",
                [(b"retry-after", b"60")])
        await task  # the answer is already streaming; let it finish
