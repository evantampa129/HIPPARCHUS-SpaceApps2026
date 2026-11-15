"""Pull the two real RW Aur cutouts of the largest-ratio published pair, and epoch a's WCS, into a JSON.

M11 shows the two exposures and their difference (b reprojected onto a's pixel
grid, exactly as backend compare() does); M12 maps a's pixel grid onto the sky
with its real WCS. Run once with the backend venv:

    backend/.venv/bin/python visualizations/manim/tools/extract_pair.py

The backend is imported read-only. We stop if a checksum or a flux differs from the evidence.
"""

import hashlib
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
warnings.simplefilter("ignore")

from hipparchus import api, compare  # noqa: E402
import reproduce_epsf as R  # noqa: E402

EVID = ROOT / "submission" / "evidence"
OUT = Path(__file__).resolve().parents[1] / "data" / "rw_aur_pair.json"
HALF = 10  # 21x21 px stamps, same size as M03


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def clean(a):
    return [[None if not np.isfinite(v) else float(v) for v in row] for row in np.asarray(a, dtype=float)]


def main():
    t = {x["id"]: x for x in api.TARGETS}["rw_aur"]
    ev = json.loads((EVID / "rw_aur_spherex-d1.json").read_text())
    top = max(ev["comparisons"], key=lambda c: c["flux_ratio"])
    epochs = {e["obs_id"]: e for e in ev["epochs"]}
    paths = R.epoch_paths(t)
    eps = {}
    for oid in (top["a"], top["b"]):
        want = epochs[oid]["provenance"]["cutout"]["sha256"]
        assert sha(paths[oid]) == want, f"{oid}: cached cutout does not match the evidence checksum"
        eps[oid] = R.load_epoch(paths[oid], oid, t)
    a, b = eps[top["a"]], eps[top["b"]]

    c = compare.compare(a, b)
    for k in ("flux_a", "flux_b"):
        assert math.isclose(c[k]["flux"], top[k]["flux"], rel_tol=1e-9), k
    assert math.isclose(c["significance"], top["significance"], rel_tol=1e-9)
    arr = c["_arrays"]

    xi, yi = int(round(a.x)), int(round(a.y))
    sl = (slice(yi - HALF, yi + HALF + 1), slice(xi - HALF, xi + HALF + 1))
    # Stamps with each epoch's own sky removed, the same subtraction the difference uses.
    sa = arr["a"][sl] - c["flux_a"]["sky"]
    sb = arr["b"][sl] - c["flux_b"]["sky"]

    # WCS of epoch a, sampled on the pixel-edge lattice of the stamp (22 x 22 points)
    # with the full celestial WCS (TAN-SIP), so the scene needs no astropy.
    ex = np.arange(xi - HALF - 0.5, xi + HALF + 1.0, 1.0)
    ey = np.arange(yi - HALF - 0.5, yi + HALF + 1.0, 1.0)
    gx, gy = np.meshgrid(ex, ey)
    ra, dec = a.wcs.pixel_to_world_values(gx, gy)
    sx, sy = a.wcs.world_to_pixel_values(ev["ra"], ev["dec"])
    assert math.isclose(float(sx), a.x, abs_tol=1e-6) and math.isclose(float(sy), a.y, abs_tol=1e-6)

    out = {
        "what": "real SPHEREx pixels of RW Aur (zodi model and local sky removed, MJy/sr): largest-ratio published pair; "
                "b reprojected onto a's grid as in backend compare(); a's WCS sampled on the stamp's pixel edges",
        "a": top["a"], "b": top["b"],
        "cutout_sha256": {oid: epochs[oid]["provenance"]["cutout"]["sha256"] for oid in (top["a"], top["b"])},
        "cutout_file": {oid: paths[oid].name for oid in (top["a"], top["b"])},
        "stamp_origin_px": [xi - HALF, yi - HALF],
        "star_xy": [float(a.x), float(a.y)],
        "star_xy_in_stamp": [float(a.x - (xi - HALF)), float(a.y - (yi - HALF))],
        "cutout_shape": list(a.image.shape),
        "stamp_a": clean(sa), "stamp_b": clean(sb), "stamp_diff": clean(arr["diff"][sl]),
        "stamp_bad": arr["bad"][sl].astype(int).tolist(),
        "flux": {"a": c["flux_a"]["flux"], "b": c["flux_b"]["flux"], "significance": c["significance"]},
        "wcs": {"ctype": list(a.wcs.wcs.ctype), "edge_x": ex.tolist(), "edge_y": ey.tolist(),
                "ra": ra.tolist(), "dec": dec.tolist()},
    }
    OUT.write_text(json.dumps(out) + "\n")
    print("wrote", OUT, top["a"], "->", top["b"])


if __name__ == "__main__":
    main()
