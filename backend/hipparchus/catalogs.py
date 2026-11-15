"""Check the target positions against SIMBAD and Gaia DR3.

This does not change any measurement. It answers three questions per target:
is the preset position on the right star, how far off is it in SPHEREx pixels,
and are there other Gaia stars inside our photometry aperture (blending)?

The main CDS servers in Strasbourg were offline in November 2026 after a
cybersecurity incident (notice on https://cds.unistra.fr/, 9 Nov 2026), and the
ESA Gaia archive did not answer. So we ask the mirrors that CDS and IRSA point
to, in order, and record which one answered. If none answers we say so and
return nothing: a catalogue match is never made up.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math

import httpx
from astropy.io import ascii as asc

# We try the SIMBAD TAP mirrors CDS listed during the outage, then the main server.
SIMBAD_TAP = (
    "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync",
    "https://simbad.idia.ac.za/simbad/sim-tap/sync",
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
)
# For Gaia DR3 we try IRSA's Gator (NASA/IPAC), then VizieR at CfA Harvard (I/355).
GATOR_URL = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"
VIZIER_URL = "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv"

GAIA_EPOCH = 2016.0      # Gaia DR3 reference epoch
SIMBAD_EPOCH = 2000.0    # SIMBAD basic positions are J2000, epoch 2000
SPHEREX_EPOCH = 2026.0   # middle of our data (Aug 2025 - Sep 2026)
PIXEL_ARCSEC = 6.15
APERTURE_ARCSEC = 2 * PIXEL_ARCSEC   # photometry aperture radius (2 px)
# Barnard's Star moves 10"/yr, so a narrow cone around a 2026 position would
# miss its 2016 Gaia entry. 120" covers ten years of the fastest star we use.
SEARCH_ARCSEC = 120.0


def propagate(ra: float, dec: float, pmra: float | None, pmdec: float | None,
              from_epoch: float, to_epoch: float) -> tuple[float, float]:
    """Move a position by its proper motion (mas/yr; pmra includes cos dec).

    We treat the motion as linear: over ~25 years the error stays far below a
    SPHEREx pixel even for Barnard's Star.
    """
    if pmra is None or pmdec is None or not math.isfinite(pmra) or not math.isfinite(pmdec):
        return ra, dec
    dt = to_epoch - from_epoch
    dec2 = dec + pmdec * dt / 3.6e6
    ra2 = ra + pmra * dt / 3.6e6 / math.cos(math.radians(dec))
    return ra2 % 360.0, dec2


def sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angular separation (haversine), in arcseconds."""
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return math.degrees(2 * math.asin(math.sqrt(min(1.0, a)))) * 3600.0


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _get(url: str, params: dict, timeout: float) -> tuple[str, str]:
    r = httpx.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text, hashlib.sha256(r.content).hexdigest()


def simbad_cone(ra: float, dec: float, radius_arcsec: float = SEARCH_ARCSEC,
                timeout: float = 40.0) -> dict:
    """SIMBAD objects around a position, from the first mirror that answers."""
    q = ("SELECT main_id, ra, dec, pmra, pmdec, otype FROM basic WHERE "
         f"CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius_arcsec / 3600.0}))=1")
    params = {"request": "doQuery", "lang": "adql", "format": "csv", "query": q}
    errors = []
    for url in SIMBAD_TAP:
        try:
            text, sha = _get(url, params, timeout)
            t = list(csv.DictReader(io.StringIO(text)))
            if t and "main_id" not in t[0]:
                raise ValueError("not a SIMBAD table")  # e.g. an HTML error page
        except Exception as e:  # network error, HTTP error or an HTML error page
            errors.append(f"{url}: {type(e).__name__}")
            continue
        rows = [{"main_id": r["main_id"], "ra": _num(r["ra"]), "dec": _num(r["dec"]),
                 "pmra": _num(r["pmra"]), "pmdec": _num(r["pmdec"]), "otype": r["otype"]}
                for r in t]
        return {"status": "ok", "server": url, "query": q, "sha256": sha, "rows": rows, "errors": errors}
    return {"status": "unreachable", "errors": errors, "rows": []}


def gaia_cone(ra: float, dec: float, radius_arcsec: float = SEARCH_ARCSEC,
              timeout: float = 60.0) -> dict:
    """Gaia DR3 sources around a position: IRSA Gator first, VizieR mirror second."""
    errors = []
    cols = "source_id,ra,dec,pmra,pmdec,phot_g_mean_mag"
    try:
        params = {"catalog": "gaia_dr3_source", "spatial": "cone", "objstr": f"{ra} {dec}",
                  "radius": radius_arcsec, "outfmt": 1, "selcols": cols}
        text, sha = _get(GATOR_URL, params, timeout)
        t = asc.read(io.StringIO(text), format="ipac")
        rows = [{"source_id": str(r["source_id"]), "ra": _num(r["ra"]), "dec": _num(r["dec"]),
                 "pmra": _num(r["pmra"]), "pmdec": _num(r["pmdec"]), "g": _num(r["phot_g_mean_mag"])}
                for r in t]
        return {"status": "ok", "server": GATOR_URL, "params": params, "sha256": sha, "rows": rows,
                "errors": errors}
    except Exception as e:
        errors.append(f"{GATOR_URL}: {type(e).__name__}")
    try:
        params = {"-source": "I/355/gaiadr3", "-c": f"{ra} {dec:+}", "-c.rs": radius_arcsec,
                  "-out": "Source,RA_ICRS,DE_ICRS,pmRA,pmDE,Gmag", "-out.max": 5000}
        text, sha = _get(VIZIER_URL, params, timeout)
        # VizieR TSV: comment lines, header, units line, dashes line, then data.
        lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
        rows = []
        for ln in lines[3:]:
            f = ln.split("\t")
            rows.append({"source_id": f[0].strip(), "ra": _num(f[1]), "dec": _num(f[2]),
                         "pmra": _num(f[3]), "pmdec": _num(f[4]), "g": _num(f[5])})
        return {"status": "ok", "server": VIZIER_URL, "params": params, "sha256": sha, "rows": rows,
                "errors": errors}
    except Exception as e:
        errors.append(f"{VIZIER_URL}: {type(e).__name__}")
    return {"status": "unreachable", "errors": errors, "rows": []}


def match(name: str, ra: float, dec: float, simbad: dict, gaia: dict,
          epoch: float = SPHEREX_EPOCH) -> dict:
    """Compare the preset position with both catalogues at the SPHEREx epoch.

    The SIMBAD object is the one whose name matches `name` if there is one,
    otherwise the nearest after proper motion. The Gaia counterpart is the
    nearest Gaia source to that SIMBAD position (both moved to `epoch`).
    """
    out: dict = {"preset": {"ra": ra, "dec": dec}, "epoch": epoch}
    sim = None
    for r in simbad.get("rows", []):
        r["ra_epoch"], r["dec_epoch"] = propagate(r["ra"], r["dec"], r["pmra"], r["pmdec"], SIMBAD_EPOCH, epoch)
        r["sep_from_preset_arcsec"] = sep_arcsec(ra, dec, r["ra_epoch"], r["dec_epoch"])
    named = [r for r in simbad.get("rows", []) if r["main_id"].replace(" ", "") == name.replace(" ", "")]
    pool = named or simbad.get("rows", [])
    if pool:
        sim = min(pool, key=lambda r: r["sep_from_preset_arcsec"])
    out["simbad"] = sim
    ref_ra, ref_dec = (sim["ra_epoch"], sim["dec_epoch"]) if sim else (ra, dec)

    srcs = []
    for r in gaia.get("rows", []):
        if r["ra"] is None or r["dec"] is None:
            continue
        r["ra_epoch"], r["dec_epoch"] = propagate(r["ra"], r["dec"], r["pmra"], r["pmdec"], GAIA_EPOCH, epoch)
        r["sep_from_target_arcsec"] = sep_arcsec(ref_ra, ref_dec, r["ra_epoch"], r["dec_epoch"])
        srcs.append(r)
    srcs.sort(key=lambda r: r["sep_from_target_arcsec"])
    # We only accept a Gaia counterpart within one SPHEREx pixel of the target, and
    # report a star without one (e.g. WISE 0855, far too red for Gaia) as such.
    cp = srcs[0] if srcs and srcs[0]["sep_from_target_arcsec"] < PIXEL_ARCSEC else None
    out["gaia_counterpart"] = cp
    out["gaia_in_aperture"] = [s for s in srcs if s["sep_from_target_arcsec"] <= APERTURE_ARCSEC]
    off = sep_arcsec(ra, dec, ref_ra, ref_dec) if sim else None
    out["preset_offset_arcsec"] = off
    out["preset_offset_px"] = off / PIXEL_ARCSEC if off is not None else None
    return out
