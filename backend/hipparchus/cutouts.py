"""Download small FITS cutouts around a target and keep them in a local cache."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx

from hipparchus.archive import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"

# A full SPHEREx detector image is about 70 MB. A cutout of 0.05 deg (about 29
# pixels at 6.15 arcsec/px) is a few MB and covers the target plus enough sky
# around it to estimate the local background.
DEFAULT_SIZE_DEG = 0.05

# We cap every file, so a wrong URL can never fill the disk with a full image.
MAX_BYTES = 20 * 1024 * 1024


def _key(access_url: str, ra: float, dec: float, size: float) -> str:
    # We build the cache key from everything that defines the cutout, so the
    # same request always maps to the same file, and a different one never does.
    raw = f"{access_url}|{ra:.6f}|{dec:.6f}|{size:.4f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def fetch(access_url: str, ra: float, dec: float, size: float = DEFAULT_SIZE_DEG,
          retries: int = 2, timeout: float = 120.0) -> dict:
    """Return {path, sha256, url, cached} for a cutout centred on (ra, dec).

    IRSA's image service cuts the file on the server when the product URL gets
    `center` and `size` parameters, so only the small piece is transferred.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _key(access_url, ra, dec, size)
    path = CACHE_DIR / f"{key}.fits"
    meta_path = CACHE_DIR / f"{key}.json"

    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        # We verify the file on every reuse: a truncated download must not end up
        # silently in a science comparison.
        if hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]:
            return meta | {"path": str(path), "cached": True}

    params = {"center": f"{ra},{dec}", "size": str(size)}
    last_error = None
    for attempt in range(retries + 1):
        try:
            with httpx.stream("GET", access_url, params=params, timeout=timeout,
                              follow_redirects=True) as r:
                r.raise_for_status()
                chunks, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError(f"cutout larger than {MAX_BYTES} bytes, refusing")
                    chunks.append(chunk)
                url = str(r.request.url)
            data = b"".join(chunks)
            # Every FITS file starts with the 6-character keyword SIMPLE. An HTML
            # error page served with status 200 would fail this check.
            if not data.startswith(b"SIMPLE"):
                raise ValueError("response is not a FITS file")
            path.write_bytes(data)
            meta = {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            meta_path.write_text(json.dumps(meta))
            return meta | {"path": str(path), "cached": False}
        except (httpx.HTTPError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"cutout download failed: {last_error}")
