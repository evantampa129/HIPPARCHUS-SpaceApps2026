"""Find SPHEREx observations of a sky position in the NASA/IPAC IRSA archive."""

from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from astropy.io.votable import parse_single_table

# IRSA's image search service (IVOA SIA v2). We call it with plain HTTP rather
# than pyvo.SIA2Service: pyvo first asks for the service "capabilities" document,
# and that endpoint was returning 502 while the search itself worked fine.
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"

# DR1 is the first full data release and QR3 the latest quick release. QR2 is
# superseded and no longer served, so we leave it out on purpose.
# Order matters: when the same exposure appears in both, we keep the first (DR1
# has the newer processing).
COLLECTIONS = ("spherex_dr1", "spherex_qr3")

# Citation DOIs that IRSA publishes for these products. We put them into every
# report so each image can be traced back to its release.
RELEASE_DOI = {
    "spherex_dr1": "10.26131/IRSA678",
    "spherex_qr3": "10.26131/IRSA662",
}

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MANIFEST_DIR = DATA_DIR / "manifests"


@dataclass
class Observation:
    """One SPHEREx exposure on one detector, as listed by the archive."""

    obs_id: str          # exposure name, e.g. 2025W33_2C_0321_1
    release: str         # spherex_dr1 or spherex_qr3
    doi: str
    detector: str        # SPHEREx-D1 .. D6; each detector covers its own wavelength range
    mjd_start: float     # exposure start, Modified Julian Date (UTC)
    mjd_end: float
    exptime_s: float
    em_min_um: float     # wavelength range of the WHOLE detector, in microns
    em_max_um: float     # (the value at the target pixel is read later from the FITS)
    access_url: str      # full-detector FITS; cutouts are requested from the same URL
    publisher_did: str   # permanent IVOA identifier of the product
    release_date: str

    @property
    def mjd_mid(self) -> float:
        return 0.5 * (self.mjd_start + self.mjd_end)

    @property
    def utc_mid(self) -> str:
        # MJD 40587 is 1970-01-01, so this converts straight to a UNIX timestamp.
        ts = (self.mjd_mid - 40587.0) * 86400.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _parse(votable: bytes, release: str) -> list[Observation]:
    # use_names_over_ids: IRSA labels its columns col_0, col_1, ... and keeps the
    # real ObsCore names (s_ra, t_min, ...) in the "name" attribute.
    t = parse_single_table(io.BytesIO(votable)).to_table(use_names_over_ids=True)
    out = []
    for row in t:
        # We keep only calibrated science frames; nothing else in the collection
        # is an image we can compare.
        if str(row["dataproduct_subtype"]) != "science":
            continue
        out.append(
            Observation(
                obs_id=str(row["obs_id"]),
                release=release,
                doi=RELEASE_DOI[release],
                detector=str(row["energy_bandpassname"]),
                mjd_start=float(row["t_min"]),
                mjd_end=float(row["t_max"]),
                exptime_s=float(row["t_exptime"]),
                # ObsCore stores wavelengths in metres; we switch to microns, they are easier to read.
                em_min_um=float(row["em_min"]) * 1e6,
                em_max_um=float(row["em_max"]) * 1e6,
                access_url=str(row["access_url"]),
                publisher_did=str(row["obs_publisher_did"]),
                release_date=str(row["obs_release_date"]),
            )
        )
    return out


def _manifest_path(ra: float, dec: float) -> Path:
    # We save one manifest per position, rounded to about 0.4 arcsec, so a
    # repeated search for the same target reuses the same file.
    return MANIFEST_DIR / f"obs_{ra:.4f}_{dec:+.4f}.json"


def query(ra: float, dec: float, timeout: float = 90.0, retries: int = 2) -> dict:
    """Return every SPHEREx science exposure covering (ra, dec), oldest first.

    The answer says where the list came from: "live" for a fresh archive query,
    or "cached" when IRSA could not be reached and we fell back to the last
    manifest saved for this position. Nothing is invented if both fail.
    """
    # A tiny search circle (about 3.6 arcsec): we only want exposures that
    # contain the target itself, not ones that cover nearby sky.
    pos = f"CIRCLE {ra} {dec} 0.001"
    observations: list[Observation] = []
    sources = []
    errors = []
    for release in COLLECTIONS:
        params = {"COLLECTION": release, "POS": pos, "RESPONSEFORMAT": "VOTABLE"}
        for attempt in range(retries + 1):
            try:
                r = httpx.get(SIA_URL, params=params, timeout=timeout)
                r.raise_for_status()
                observations += _parse(r.content, release)
                # The checksum of the raw VOTable lets anyone confirm later that
                # the manifest really matches what the archive returned.
                sources.append({
                    "release": release,
                    "url": str(r.request.url),
                    "sha256": hashlib.sha256(r.content).hexdigest(),
                })
                break
            except (httpx.HTTPError, ValueError) as e:
                if attempt == retries:
                    errors.append(f"{release}: {e}")
                else:
                    time.sleep(2 * (attempt + 1))  # IRSA sometimes returns 502s, so we back off briefly

    if errors and not observations:
        cached = _manifest_path(ra, dec)
        if cached.exists():
            m = json.loads(cached.read_text())
            m["archive_status"] = "cached"
            m["errors"] = errors
            return m
        return {"archive_status": "unavailable", "errors": errors, "observations": []}

    # The same exposure can be listed in both releases. We keep the first one
    # (DR1, see COLLECTIONS) and drop the rest.
    seen: dict[tuple, Observation] = {}
    for o in observations:
        seen.setdefault((o.obs_id, o.detector), o)
    ordered = sorted(seen.values(), key=lambda o: o.mjd_start)

    manifest = {
        "archive_status": "live" if not errors else "partial",
        "queried_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ra": ra,
        "dec": dec,
        "sources": sources,
        "errors": errors,
        "observations": [asdict(o) | {"mjd_mid": o.mjd_mid, "utc_mid": o.utc_mid} for o in ordered],
    }
    # We only let a complete answer replace the saved listing. A partial one (one
    # release timed out) would otherwise overwrite a full listing with fewer
    # exposures, and the offline fallback would then silently lose data.
    if not errors:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        _manifest_path(ra, dec).write_text(json.dumps(manifest, indent=1))
    return manifest
