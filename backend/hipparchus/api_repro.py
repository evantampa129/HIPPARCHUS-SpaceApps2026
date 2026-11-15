"""Routes for the reproduction bundles and mini reports.

Both are built from the published evidence in submission/evidence and served
from submission/bundles when already built there; nothing is recomputed from
the archive on request. Include in api.py with:

    from hipparchus import api_repro
    app.include_router(api_repro.router)
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from hipparchus import bundle, minireport

router = APIRouter(tags=["reproduction"])

SOURCE_HEADER = {"X-Hipparchus-Source": "published-evidence; cached, not recomputed"}

# Built once per process when no prebuilt file exists; the evidence does not
# change while the server runs.
_MEMO: dict[tuple[str, str], bytes] = {}
_LOCK = threading.Lock()


def _check(case: str) -> None:
    if case not in bundle.CASES:
        raise HTTPException(404, f"unknown case {case!r}; known: {', '.join(bundle.CASES)}")


def _prebuilt(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


@router.get("/reproduce")
def list_cases():
    return [{"case": c, "title": s["title"], "bundle": f"/reproduce/{c}.zip", "report": f"/report/{c}.html",
             "built_from": "published evidence (cached, not recomputed)"} for c, s in bundle.CASES.items()]


@router.get("/reproduce/{case}.zip")
def reproduce_zip(case: str):
    _check(case)
    with _LOCK:
        data = _MEMO.get(("zip", case)) or _prebuilt(bundle.BUNDLE_DIR / f"{case}.zip")
        if data is None:
            data = bundle.build(case).read_bytes()
        _MEMO[("zip", case)] = data
    return Response(data, media_type="application/zip",
                    headers=SOURCE_HEADER | {"Content-Disposition": f'attachment; filename="hipparchus_{case}.zip"'})


@router.get("/report/{case}.html", response_class=HTMLResponse)
def report_html(case: str):
    _check(case)
    with _LOCK:
        data = _MEMO.get(("html", case)) or _prebuilt(minireport.REPORT_DIR / f"{case}.html")
        if data is None:
            data = minireport.render_html(case).encode()
        _MEMO[("html", case)] = data
    return HTMLResponse(data, headers=SOURCE_HEADER)
