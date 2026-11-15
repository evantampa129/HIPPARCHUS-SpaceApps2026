"""Pull the real RW Aur pixels used by M03 (aperture) and M04 (ePSF) into a small JSON.

We run this once with the backend venv, because it needs the backend's FITS
loader and ePSF fit; the Manim venv then only reads the JSON. The backend is
imported read-only, nothing there is changed.

    backend/.venv/bin/python visualizations/manim/tools/extract_pixels.py
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
OUT = Path(__file__).resolve().parents[1] / "data" / "rw_aur_pixels.json"
OBS = "2025W36_1A_0233_2"  # first epoch of the strongest published pair
HALF = 10                    # 21x21 px stamp for the aperture scene


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    t = {x["id"]: x for x in api.TARGETS}["rw_aur"]
    ev = json.loads((EVID / "rw_aur_spherex-d1.json").read_text())
    epsf_ev = json.loads((EVID / "epsf_check.json").read_text())["targets"]["rw_aur"]["fits"][OBS]
    want = {e["obs_id"]: e for e in ev["epochs"]}[OBS]["provenance"]["cutout"]["sha256"]
    path = R.epoch_paths(t)[OBS]
    # We only accept the cutout if its checksum is the one in the evidence file.
    assert sha(path) == want, "cached cutout does not match the evidence checksum"

    ep, e, f = R.fit_epoch(path, OBS, t)
    assert f["ok"]
    # Same numbers as the published experimental check, or we stop.
    assert math.isclose(f["chi2_red"], epsf_ev["chi2_red"], rel_tol=1e-6)
    assert math.isclose(f["amp"], epsf_ev["amp"], rel_tol=1e-6)

    xi, yi = int(round(ep.x)), int(round(ep.y))
    stamp = ep.image[yi - HALF:yi + HALF + 1, xi - HALF:xi + HALF + 1]
    bad = ep.bad[yi - HALF:yi + HALF + 1, xi - HALF:xi + HALF + 1]
    ph = compare.photometry(ep.image, ep.variance, ep.bad, ep.x, ep.y)
    comp = next(c for c in ev["comparisons"] if c["a"] == OBS)
    assert math.isclose(ph["flux"], comp["flux_a"]["flux"], rel_tol=1e-9)

    # Residual in units of each pixel's own sigma, so the colour scale means the
    # same thing as chi2; we check it adds back up to the published chi2_red.
    i0, i1, j0, j1 = f["box"]
    rsig = f["residual"] / np.sqrt(ep.variance[i0:i1, j0:j1])
    assert math.isclose(np.nansum(rsig ** 2) / f["dof"], f["chi2_red"], rel_tol=1e-6)

    def clean(a):
        return [[None if not np.isfinite(v) else float(v) for v in row] for row in np.asarray(a)]

    out = {
        "what": "real SPHEREx pixels of RW Aur (zodi model removed, MJy/sr), one epoch",
        "obs_id": OBS,
        "cutout_sha256": want,
        "cutout_file": path.name,
        "star_xy_in_stamp": [float(ep.x - (xi - HALF)), float(ep.y - (yi - HALF))],
        "stamp": clean(stamp),
        "stamp_bad": bad.astype(int).tolist(),
        "aperture_px": 2.0,
        "annulus_px": [4.0, 7.0],
        "photometry": {k: float(v) for k, v in ph.items()},
        "epsf": {
            "data": clean(f["data"]), "model": clean(f["model"]), "residual": clean(f["residual"]),
            "residual_sigma": clean(rsig),
            "chi2_red": f["chi2_red"], "dof": f["dof"], "amp": f["amp"],
            "box": f["box"],
            "epsf_source": json.loads((EVID / "epsf_check.json").read_text())["targets"]["rw_aur"]["epochs"][OBS]["epsf_source"],
        },
    }
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, "chi2_red", round(f["chi2_red"], 3), "flux", round(ph["flux"], 3))


if __name__ == "__main__":
    main()
