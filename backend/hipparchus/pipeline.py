"""From a sky position to a list of valid, refused and null-test epoch pairs."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations

from hipparchus import archive, cutouts, quality
from hipparchus.compare import compare, compatibility


def load_epochs(ra: float, dec: float, detector: str, limit: int | None = None,
                size: float = cutouts.DEFAULT_SIZE_DEG) -> dict:
    """Download and check every exposure of one detector that covers (ra, dec)."""
    manifest = archive.query(ra, dec)
    obs = [o for o in manifest["observations"] if o["detector"] == detector]
    if limit:
        obs = obs[:limit]

    def one(o):
        try:
            c = cutouts.fetch(o["access_url"], ra, dec, size)
            ep = quality.load(c["path"], o["obs_id"], ra, dec)
            return ep, {"obs": o, "cutout": {k: c[k] for k in ("url", "sha256", "cached")}}
        except Exception as e:  # one broken file must not stop the whole target
            return None, {"obs": o, "error": str(e)}

    # Downloads are I/O-bound, so a few threads cut the wait roughly in proportion.
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(one, obs))
    epochs = [ep for ep, _ in results if ep is not None]
    prov = {ep.obs_id: p for ep, p in results if ep is not None}
    failed = [p for ep, p in results if ep is None]
    return {"manifest": manifest, "epochs": epochs, "provenance": prov, "failed": failed}


def analyze(ra: float, dec: float, detector: str, limit: int | None = None) -> dict:
    loaded = load_epochs(ra, dec, detector, limit)
    epochs = sorted(loaded["epochs"], key=lambda e: e.mjd)

    refusals: Counter = Counter()
    nulls, comparisons = [], []
    for a, b in combinations(epochs, 2):
        v = compatibility(a, b)
        if not v.comparable:
            # Count every cause, so the summary can say how many pairs failed
            # on wavelength and how many on flagged pixels (a pair can have both).
            refusals.update(set(v.codes))
            continue
        (nulls if v.kind == "null_test" else comparisons).append(compare(a, b))

    return {
        "ra": ra, "dec": dec, "detector": detector,
        "archive_status": loaded["manifest"]["archive_status"],
        # The archive queries behind this result, with the checksum of each raw answer.
        "archive_queries": loaded["manifest"].get("sources", []),
        "n_epochs": len(epochs),
        "n_usable": sum(e.usable for e in epochs),
        "epochs": [
            {"obs_id": e.obs_id, "mjd": e.mjd, "date_obs": e.date_obs,
             "wavelength_um": e.wavelength_um, "bandwidth_um": e.bandwidth_um,
             "usable": e.usable, "issues": [i.__dict__ for i in e.issues],
             "provenance": loaded["provenance"][e.obs_id]}
            for e in epochs
        ],
        "failed_downloads": loaded["failed"],
        "refused_pairs": dict(refusals),
        "null_tests": nulls,
        "comparisons": comparisons,
        "_epochs": epochs,  # kept in memory for image rendering; not serialised
    }
