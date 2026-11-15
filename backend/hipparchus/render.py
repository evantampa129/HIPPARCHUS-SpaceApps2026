"""Turn epoch images and comparison arrays into PNGs for the browser."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")  # no display on a server; render straight to memory
import matplotlib.pyplot as plt
import numpy as np

# A cutout is only ~29x29 pixels. Scaling it up with "nearest" keeps every real
# pixel visible as a square, instead of smoothing it into detail that does not exist.
OUT_PX = 320


def _png(arr, cmap, vmin, vmax, mark=None, bad_color="#5a1a1a") -> bytes:
    fig = plt.figure(figsize=(OUT_PX / 100, OUT_PX / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    shown = np.ma.masked_invalid(arr)
    cm = plt.get_cmap(cmap).copy()
    cm.set_bad(bad_color)  # masked (flagged or missing) pixels get their own colour, never sky
    ax.imshow(shown, origin="lower", cmap=cm, vmin=vmin, vmax=vmax, interpolation="nearest")
    if mark is not None:
        # Thin ring at the target position, with the radius of the photometry aperture.
        from hipparchus.quality import APERTURE_PX
        ax.add_patch(plt.Circle(mark, APERTURE_PX, fill=False, color="#7fd4ff", lw=1.2))
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def stretch_limits(*images) -> tuple[float, float]:
    """One brightness scale shared by all images, so a blink compares like with like."""
    vals = np.concatenate([np.asarray(i)[np.isfinite(i)].ravel() for i in images])
    if vals.size == 0:
        return 0.0, 1.0
    # Top of the scale at the brightest pixel: with a percentile the star's core
    # would clip to white in both epochs and the blink would hide its change.
    return float(np.percentile(vals, 1)), float(vals.max())


def epoch_png(image, bad, x, y, limits) -> bytes:
    img = np.where(bad, np.nan, image)
    # asinh-like view: compress the bright core so faint sky stays visible.
    lo, hi = limits
    scaled = np.arcsinh((img - lo) / max((hi - lo) / 20, 1e-9))
    return _png(scaled, "gray", 0, np.arcsinh(20), mark=(x, y))


def diff_png(diff, x, y) -> bytes:
    lim = float(np.nanpercentile(np.abs(diff), 99.5)) if np.isfinite(diff).any() else 1.0
    # Grey for masked pixels: on a red/blue map, dark red would read as "brighter".
    return _png(diff, "RdBu_r", -lim, lim, mark=(x, y), bad_color="#6b6b6b")


def z_png(z, x, y) -> bytes:
    # Fixed scale of +-5 sigma: anything saturating the colours is significant.
    return _png(z, "RdBu_r", -5, 5, mark=(x, y), bad_color="#6b6b6b")
