"""Load one SPHEREx cutout and decide whether it can be used for a measurement."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from astropy import log
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

# Reading the spectral WCS makes astropy log a long INFO note about SIP keywords.
# It does not affect the result, and in a web service it only floods the log.
log.setLevel("WARNING")

# Flag planes that make a pixel unusable for photometry or differencing. The
# names are read from each file's own FLAGS header (MSKNnnnn/MSKMnnnn), so if a
# future pipeline version renumbers the bits, this still selects the right ones.
# Planes left out on purpose:
#   SOURCE      marks pixels on a known catalogued source. Our target IS a source,
#               so rejecting these would reject every measurement.
#   FULLSAMPLE  only says the full readout history exists.
#   DICHROIC    lower throughput near the dichroic edge. That is a calibration
#               effect and is reported as a warning, not a hard rejection.
#   PHANMISS    phantom correction not applied; also a warning (see WARN_PLANES).
BAD_PLANES = {
    "TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT", "COLD",
    "NONLINEAR", "PERSIST", "OUTLIER", "CROSSTALK", "GHOST", "GHOST_FPA",
    "GHOST_EXT", "STREAK", "BLOOM", "SNOWBALL", "HALO",
}
WARN_PLANES = {"DICHROIC", "PHANMISS"}

# Radius (pixels) of the region around the target that must be clean. SPHEREx
# PSFs have a FWHM of about 1.5 pixels, so a 2-pixel radius contains most of
# the light of a point source.
APERTURE_PX = 2.0


@dataclass
class Issue:
    code: str       # short machine-readable reason, e.g. "flagged_pixels"
    severity: str   # "reject" stops the comparison, "warn" is shown but allowed
    message: str    # one sentence a person can read


@dataclass
class Epoch:
    """One cutout, reduced to what the comparison needs."""

    obs_id: str
    detector: int
    mjd: float               # mid-exposure time (MJD-AVG from the header)
    date_obs: str
    image: np.ndarray        # surface brightness with the zodiacal model removed, MJy/sr
    variance: np.ndarray     # MJy^2/sr^2
    bad: np.ndarray          # True where a BAD_PLANES flag is set
    wcs: WCS                 # celestial WCS (RA/Dec <-> pixel)
    x: float                 # target position in pixels (0-based)
    y: float
    wavelength_um: float     # wavelength at the target pixel
    bandwidth_um: float      # spectral width of that pixel
    psf_fwhm_arcsec: float
    flag_counts: dict = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not any(i.severity == "reject" for i in self.issues)


def _plane_masks(header) -> dict[str, int]:
    # Build {plane name: bit value} from the header, e.g. {"HOT": 1024, ...}.
    out = {}
    for key in header:
        if key.startswith("MSKN"):
            n = key[4:]
            bit = header.get(f"MSKM{n}")
            if bit is not None:
                out[str(header[key]).strip()] = int(bit)
    return out


# Extensions the checks below cannot work without. A file that lacks one is
# refused with its name, instead of failing later with an unclear KeyError.
REQUIRED_HDUS = ("IMAGE", "FLAGS", "VARIANCE", "ZODI")


def target_pixel(wcs: WCS, ra: float, dec: float) -> tuple[float, float]:
    """Pixel position of (ra, dec). RA is taken modulo 360, so a target at
    RA 359.999 and an image centred at RA 0.001 still line up."""
    x, y = wcs.world_to_pixel_values(ra % 360.0, dec)
    return float(x), float(y)


def load(path: str, obs_id: str, ra: float, dec: float) -> Epoch:
    with warnings.catch_warnings(), fits.open(path) as h:
        missing = [n for n in REQUIRED_HDUS if n not in h]
        if missing:
            raise ValueError(f"{obs_id}: FITS file lacks the {', '.join(missing)} extension(s)")
        # The spectral WCS uses SIP-style keywords that astropy warns about. The
        # celestial solution is unaffected. We found later that astropy also applies
        # the celestial SIP terms to WCS(key="W"), so the wavelength below is read at a
        # slightly shifted pixel (up to ~18 nm on WISE 0855). We keep it unchanged so the
        # published numbers stay reproducible; spectral_cal.py and reproduce_wavecal.py
        # show that no published conclusion changes with the calibrated CWAVE/CBAND.
        warnings.simplefilter("ignore", FITSFixedWarning)

        hdr = h["IMAGE"].header
        # The archive images still contain the zodiacal light (sunlight scattered
        # by interplanetary dust). It changes with the time of year, so two
        # epochs would differ even for a constant star. Removing the pipeline's
        # ZODI model before any comparison avoids that false "variability".
        image = h["IMAGE"].data.astype(float) - h["ZODI"].data.astype(float)
        variance = h["VARIANCE"].data.astype(float)
        flags = h["FLAGS"].data.astype(np.int64)

        planes = _plane_masks(h["FLAGS"].header)
        bad_bits = sum(b for name, b in planes.items() if name in BAD_PLANES)
        warn_bits = sum(b for name, b in planes.items() if name in WARN_PLANES)

        wcs = WCS(hdr)  # celestial WCS (RA---TAN-SIP / DEC--TAN-SIP)
        x, y = target_pixel(wcs, ra, dec)

        # SPHEREx uses linear variable filters: the wavelength changes across the
        # detector. The alternate WCS "W" is a lookup table that gives the
        # wavelength and bandwidth of each pixel, so we read it AT the target.
        wave = WCS(hdr, fobj=h, key="W")
        lam, dlam = (float(v) for v in wave.pixel_to_world_values(x, y))

        ep = Epoch(
            obs_id=obs_id,
            detector=int(hdr.get("DETECTOR", 0)),
            mjd=float(hdr["MJD-AVG"]),
            date_obs=str(hdr["DATE-OBS"]),
            image=image,
            variance=variance,
            bad=(flags & bad_bits) != 0,
            wcs=wcs,
            x=x,
            y=y,
            wavelength_um=lam,
            bandwidth_um=dlam,
            psf_fwhm_arcsec=float(hdr.get("PSF_FWHM", np.nan)),
        )
        ep.issues = check(ep, flags, planes, warn_bits)
        return ep


def check(ep: Epoch, flags: np.ndarray, planes: dict[str, int], warn_bits: int) -> list[Issue]:
    """Return every reason this epoch should not, or should only cautiously, be used."""
    issues: list[Issue] = []
    ny, nx = ep.image.shape
    r = APERTURE_PX

    # 1. The target must sit inside the cutout with room for the aperture.
    #    Near a detector edge the server returns a smaller, off-centre cutout.
    if not (r <= ep.x <= nx - 1 - r and r <= ep.y <= ny - 1 - r):
        issues.append(Issue("off_edge", "reject",
                            f"Target falls at pixel ({ep.x:.1f}, {ep.y:.1f}), too close to the edge of a {nx}x{ny} cutout."))
        return issues  # the remaining checks need the aperture to exist

    yy, xx = np.mgrid[0:ny, 0:nx]
    ap = (xx - ep.x) ** 2 + (yy - ep.y) ** 2 <= r ** 2

    # 2. No unusable pixels inside the aperture. Name the flags, so the reason
    #    shown to the user is specific ("SATURATED", "PERSIST", ...).
    hit = {name: int(np.count_nonzero(ap & ((flags & bit) != 0)))
           for name, bit in planes.items() if name in BAD_PLANES}
    hit = {k: v for k, v in hit.items() if v}
    ep.flag_counts = hit
    if hit:
        names = ", ".join(f"{k} ({v} px)" for k, v in sorted(hit.items()))
        issues.append(Issue("flagged_pixels", "reject", f"Pixels on the target are flagged: {names}."))

    if np.any(ap & ((flags & warn_bits) != 0)):
        issues.append(Issue("calibration_warning", "warn",
                            "Some target pixels carry a calibration warning (DICHROIC or PHANMISS)."))

    # 3. Values must be finite, and the variance strictly positive. A zero or
    #    NaN variance would make the significance of any change meaningless.
    if not np.all(np.isfinite(ep.image[ap])):
        issues.append(Issue("nan_pixels", "reject", "The image has missing (NaN) values on the target."))
    v = ep.variance[ap]
    if not np.all(np.isfinite(v)) or np.any(v <= 0):
        issues.append(Issue("bad_variance", "reject", "The variance on the target is missing, zero or negative."))

    # 4. The wavelength lookup must have returned something physical. SPHEREx
    #    covers roughly 0.75 to 5.0 microns.
    if not (0.7 <= ep.wavelength_um <= 5.1) or not (ep.bandwidth_um > 0):
        issues.append(Issue("bad_wavelength", "reject",
                            f"The wavelength at the target ({ep.wavelength_um:.3f} um) is outside the SPHEREx range."))
    return issues
