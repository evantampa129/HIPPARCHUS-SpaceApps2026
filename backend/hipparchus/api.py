"""The HTTP API behind our web page."""

from __future__ import annotations

import hashlib
import json
import platform
import threading
from datetime import datetime, timezone

import astropy
import numpy as np
import reproject
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from hipparchus import __version__, archive, compare, cutouts, quality, render
from hipparchus.pipeline import analyze

app = FastAPI(title="HIPPARCHUS", version=__version__)

# The Vite dev server runs on another port, so the browser needs CORS to call us.
# We only serve GETs and nothing here is private, so a permissive policy is fine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# Preset targets. We use these APPROXIMATE coordinates (epoch ~2025.9) only to
# centre the cutout. The external catalogues were unreachable when we set them,
# so we don't claim catalogue precision here; we measure the star's position in
# the images themselves.
TARGETS = [
    {"id": "rw_aur", "name": "RW Aurigae", "ra": 76.956, "dec": 30.401, "detector": "SPHEREx-D1",
     "why": "Young star known to vary; unsaturated in detector 1, so a real comparison is possible."},
    {"id": "barnard", "name": "Barnard's Star", "ra": 269.4463, "dec": 4.7667, "detector": "SPHEREx-D6",
     "why": "Very bright and fast-moving. It saturates SPHEREx, so the tool must refuse to compare it."},
    {"id": "wise0855", "name": "WISE 0855-0714", "ra": 133.7600, "dec": -7.2424, "detector": "SPHEREx-D6",
     "why": "The coldest known brown dwarf: faint, so this tests the limit of the data."},
]

# We keep finished analyses in memory so we can serve the images after the JSON.
# One process, a handful of targets: a dict is enough, no database needed.
_RESULTS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _public(obj):
    # We drop in-memory fields (keys starting with "_", e.g. image arrays) and turn
    # numpy scalars into plain numbers, so the result can go out as JSON.
    if isinstance(obj, dict):
        return {k: _public(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_public(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def _config() -> dict:
    # We record everything that changes the result next to it, so anyone can
    # rerun exactly the same analysis.
    return {
        "collections": list(archive.COLLECTIONS),
        "cutout_size_deg": cutouts.DEFAULT_SIZE_DEG,
        "aperture_radius_px": quality.APERTURE_PX,
        "sky_annulus_px": [compare.SKY_INNER, compare.SKY_OUTER],
        "bad_flag_planes": sorted(quality.BAD_PLANES),
        "warning_flag_planes": sorted(quality.WARN_PLANES),
        "max_wavelength_shift_fraction_of_bandwidth": compare.MAX_DLAMBDA_FRACTION,
        "default_wavelength_source": quality.DEFAULT_WAVELENGTH_SOURCE,
        "same_visit_days": compare.SAME_VISIT_DAYS,
        "detection_sigma": compare.DETECTION_SIGMA,
        "zodi_subtracted": True,
        "software": {"hipparchus": __version__, "python": platform.python_version(),
                     "astropy": astropy.__version__, "numpy": np.__version__,
                     "reproject": reproject.__version__},
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/targets")
def targets() -> list[dict]:
    return TARGETS


ROBUSTNESS = archive.DATA_DIR.parent / "submission" / "evidence" / "robustness.json"


@app.get("/robustness/{target_id}")
def robustness(target_id: str) -> dict:
    """Stability checks for a preset, precomputed by scripts/reproduce_robustness.py.

    Served from the saved file (real SPHEREx cutouts, archive listing from the
    cache), so it answers instantly and says so; it is not a live query.
    """
    if not ROBUSTNESS.exists():
        raise HTTPException(404, "No stability report has been computed yet.")
    d = json.loads(ROBUSTNESS.read_text())
    if target_id not in d["targets"]:
        raise HTTPException(404, f"No stability report for {target_id}.")
    e = d["targets"][target_id]
    return {"source": "precomputed from cached real SPHEREx cutouts (not a live archive query)",
            "settings": d["settings"], "verdict": e["verdict"], "claims": e.get("claims", []),
            "stability": e.get("stability", []), "systematic_floor": e.get("systematic_floor"),
            "trials": e.get("trials")}


@app.get("/observations")
def observations(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90)) -> dict:
    """Every SPHEREx exposure covering the position, grouped later by the UI."""
    m = archive.query(ra, dec)
    counts: dict[str, int] = {}
    for o in m["observations"]:
        counts[o["detector"]] = counts.get(o["detector"], 0) + 1
    return {**m, "per_detector": counts}


@app.get("/analyze")
def run_analysis(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
                 detector: str = Query(..., pattern=r"^SPHEREx-D[1-6]$"),
                 limit: int | None = Query(None, ge=2, le=200),
                 wavelength_source: str | None = Query(None, pattern=r"^(wcs|wcs_nosip|cwave)$")) -> dict:
    """Download, check and compare every epoch of one detector. Slow the first time."""
    src = wavelength_source or quality.DEFAULT_WAVELENGTH_SOURCE
    # We keep the old key for the default source, so existing analysis ids stay valid.
    tag = "" if src == "wcs" else f"|{src}"
    key = hashlib.sha256(f"{ra:.6f}|{dec:.6f}|{detector}|{limit}{tag}".encode()).hexdigest()[:16]
    with _LOCK:
        if key in _RESULTS:
            return _RESULTS[key]["public"]
    r = analyze(ra, dec, detector, limit, wavelength_source=src)
    if r["archive_status"] == "unavailable":
        raise HTTPException(503, "The IRSA archive could not be reached and no cached listing exists for this position.")
    r["analysis_id"] = key
    r["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    r["config"] = _config()
    # We number the pairs so the UI can ask for their images.
    for i, c in enumerate(r["comparisons"] + r["null_tests"]):
        c["pair_id"] = i
    pub = _public(r)
    with _LOCK:
        _RESULTS[key] = {"full": r, "public": pub}
    return pub


def _get(aid: str) -> dict:
    with _LOCK:
        if aid not in _RESULTS:
            raise HTTPException(404, "Unknown analysis; run /analyze first.")
        return _RESULTS[aid]["full"]


@app.get("/analysis/{aid}/epoch/{obs_id}.png")
def epoch_image(aid: str, obs_id: str) -> Response:
    r = _get(aid)
    ep = next((e for e in r["_epochs"] if e.obs_id == obs_id), None)
    if ep is None:
        raise HTTPException(404, "No such epoch in this analysis.")
    # We use one brightness scale for every epoch of the target, so the playback
    # shows real changes and not changes of display stretch.
    if "_limits" not in r:
        r["_limits"] = render.stretch_limits(*[np.where(e.bad, np.nan, e.image) for e in r["_epochs"] if e.usable] or
                                             [r["_epochs"][0].image])
    return Response(render.epoch_png(ep.image, ep.bad, ep.x, ep.y, r["_limits"]), media_type="image/png")


@app.get("/analysis/{aid}/pair/{pid}/{kind}.png")
def pair_image(aid: str, pid: int, kind: str) -> Response:
    r = _get(aid)
    pairs = r["comparisons"] + r["null_tests"]
    if not 0 <= pid < len(pairs) or kind not in ("a", "b", "diff", "z"):
        raise HTTPException(404, "No such pair or image kind.")
    c = pairs[pid]
    arr = c["_arrays"]
    ep_a = next(e for e in r["_epochs"] if e.obs_id == c["a"])
    if kind in ("a", "b"):
        lim = render.stretch_limits(arr["a"], arr["b"])
        bad = ep_a.bad | ~np.isfinite(arr[kind])
        png = render.epoch_png(arr[kind], bad, ep_a.x, ep_a.y, lim)
    elif kind == "diff":
        png = render.diff_png(arr["diff"], ep_a.x, ep_a.y)
    else:
        png = render.z_png(arr["z"], ep_a.x, ep_a.y)
    return Response(png, media_type="image/png")


@app.get("/analysis/{aid}/evidence.json")
def evidence(aid: str) -> Response:
    """The full result as a downloadable file: identifiers, checksums, settings and outputs."""
    r = _get(aid)
    body = json.dumps(_public(r), indent=1)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="hipparchus_{aid}.json"'})

# We keep the explorer endpoints (sky, spectrum, native pixels) in their own router.
from hipparchus.api_explore import router as explore_router  # noqa: E402
app.include_router(explore_router)

# Reproduction bundles and mini reports, served from the published evidence.
from hipparchus import api_repro  # noqa: E402
app.include_router(api_repro.router)
