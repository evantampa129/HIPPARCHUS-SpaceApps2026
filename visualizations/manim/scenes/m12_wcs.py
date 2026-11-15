"""M12: a real cutout's pixel grid carried onto RA/Dec by its own WCS (TAN-SIP), with RW Aur marked."""

import math

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, ApplyPointwiseFunction, Create, Dot, FadeIn, FadeOut,
                   Line, ReplacementTransform, VGroup, Indicate)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel
from hviz.style import GEOMETRY, GOLD, GRID, MUTED, OBSERVED, TEXT, HScene, T, badge

EVIDENCE = ["rw_aur_spherex-d1.json"]
S = 0.19          # screen units per native pixel
CENTRE = np.array([-3.5, -0.25, 0.0])


class Sky:
    """Bilinear interpolation of the RA/Dec lattice sampled from the real WCS (tools/extract_pair.py)."""

    def __init__(self, p):
        w = p["wcs"]
        self.ex, self.ey = np.array(w["edge_x"]), np.array(w["edge_y"])
        self.ra, self.dec = np.array(w["ra"]), np.array(w["dec"])

    def __call__(self, x, y):
        fx = np.clip((x - self.ex[0]) / (self.ex[1] - self.ex[0]), 0, len(self.ex) - 1.000001)
        fy = np.clip((y - self.ey[0]) / (self.ey[1] - self.ey[0]), 0, len(self.ey) - 1.000001)
        j, i = int(fx), int(fy)
        u, v = fx - j, fy - i

        def lerp(a):
            return ((1 - u) * (1 - v) * a[i, j] + u * (1 - v) * a[i, j + 1]
                    + (1 - u) * v * a[i + 1, j] + u * v * a[i + 1, j + 1])
        return float(lerp(self.ra)), float(lerp(self.dec))


def numbers():
    p = D.pair()
    ev = D.target("rw_aur")
    if p is None:
        return {"conceptual": True}
    sky = Sky(p)
    sx, sy = p["star_xy"]
    ra_s, dec_s = sky(sx, sy)
    # Pixel scale and orientation from the sampled WCS around the star (finite differences, 1 px).
    cosd = math.cos(math.radians(dec_s))
    rx, dx = sky(sx + 0.5, sy)
    lx, ldx = sky(sx - 0.5, sy)
    ry, dy = sky(sx, sy + 0.5)
    ly, ldy = sky(sx, sy - 0.5)
    J = np.array([[-(rx - lx) * cosd, -(ry - ly) * cosd], [dx - ldx, dy - ldy]]) * 3600  # arcsec / px (east, north)
    scale = math.sqrt(abs(np.linalg.det(J)))
    # Angle of +y (pixel up) east of north.
    pa_y = math.degrees(math.atan2(J[0, 1], J[1, 1]))
    return {"conceptual": False, "obs_id": p["a"], "star_xy": (sx, sy), "ra": ev["ra"], "dec": ev["dec"],
            "ra_interp": ra_s, "dec_interp": dec_s, "scale_arcsec": scale, "pa_y_deg": pa_y,
            "ctype": p["wcs"]["ctype"], "shape": p["cutout_shape"],
            "pix_text": f"RW Aur at pixel (x, y) = ({sx:.2f}, {sy:.2f})",
            "sky_text": f"RA {ev['ra']:.3f}°, Dec +{ev['dec']:.3f}°" if ev["dec"] >= 0 else f"RA {ev['ra']:.3f}°, Dec {ev['dec']:.3f}°",
            "lines": [f'{p["a"]} · cutout {p["cutout_shape"][1]} × {p["cutout_shape"][0]} px',
                      f'WCS from its FITS header: {p["wcs"]["ctype"][0].strip()} / {p["wcs"]["ctype"][1].strip()}',
                      f"{scale:.2f}″ per pixel · pixel +y points {abs(pa_y):.1f}° {'east' if pa_y >= 0 else 'west'} of north",
                      "(x, y) → (RA, Dec): each grid point is moved",
                      "by this WCS, not by a sketch"]}


class M12WCS(HScene):
    SCENE_ID = "M12"
    TITLE = "From pixels to sky: the cutout's own WCS"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1, NASA/IPAC IRSA · cutout SHA-256 in rw_aur_spherex-d1.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        if n["conceptual"]:
            self.add(badge("CONCEPTUAL"), T("Real WCS not available on this machine", 24))
            self.wait(3)
            return
        p = D.pair()
        sky = Sky(p)
        ex, ey = sky.ex, sky.ey
        x0, x1, y0, y1 = ex[0], ex[-1], ey[0], ey[-1]
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2

        def pix2scr(x, y):
            return CENTRE + np.array([(x - xc) * S, (y - yc) * S, 0.0])

        pix = Panel((x0, x1), (y0, y1), (x1 - x0) * S, (y1 - y0) * S, x_label="pixel x", y_label="pixel y",
                    x_ticks=[(v, f"{v:.0f}") for v in range(int(x0) + 2, int(x1) + 1, 5)],
                    y_ticks=[(v, f"{v:.0f}") for v in range(int(y0) + 2, int(y1) + 1, 5)],
                    grid=False, size=14)
        pix.shift(CENTRE - pix.box.get_center())

        # Sky axes at the same screen scale: RA grows to the left (east), as on the sky.
        ra_all, dec_all = sky.ra.ravel(), sky.dec.ravel()
        cosd = math.cos(math.radians(n["dec"]))
        pad = 1.2 * n["scale_arcsec"] / 3600
        r_lo, r_hi = ra_all.min() - pad / cosd, ra_all.max() + pad / cosd
        d_lo, d_hi = dec_all.min() - pad, dec_all.max() + pad
        k = S / (n["scale_arcsec"] / 3600)    # screen units per degree on the sky
        skyp = Panel((r_hi, r_lo), (d_lo, d_hi), (r_hi - r_lo) * cosd * k, (d_hi - d_lo) * k,
                     x_label="RA (°, east ←)", y_label="Dec (°)",
                     x_ticks=[(v, f"{v:.2f}") for v in np.arange(math.ceil(r_lo * 100) / 100, r_hi, 0.01)],
                     y_ticks=[(v, f"{v:.2f}") for v in np.arange(math.ceil(d_lo * 100) / 100, d_hi, 0.01)],
                     grid=False, size=14)
        skyp.yl.shift(LEFT * 0.3)  # the Dec tick labels are wider than the pixel ones
        # Place it so the star stays where it is on screen: only the WCS moves things.
        skyp.shift(pix2scr(*n["star_xy"]) - skyp.c2p(n["ra"], n["dec"]))

        def wcs_map(pt):
            x = (pt[0] - CENTRE[0]) / S + xc
            y = (pt[1] - CENTRE[1]) / S + yc
            return skyp.c2p(*sky(x, y))

        grid = VGroup()
        for x in ex:
            grid.add(Line(pix2scr(x, y0), pix2scr(x, y1), stroke_color=GEOMETRY, stroke_width=1.1, stroke_opacity=0.55))
        for y in ey:
            grid.add(Line(pix2scr(x0, y), pix2scr(x1, y), stroke_color=GEOMETRY, stroke_width=1.1, stroke_opacity=0.55))
        for ln in grid:
            ln.insert_n_curves(20)  # so the map can bend lines if the distortion asks for it
        ghost = grid.copy().set_stroke(MUTED, 1.3, 0.6)

        star = Dot(pix2scr(*n["star_xy"]), radius=0.08, color=OBSERVED)
        lab_pix = T(n["pix_text"], 16, OBSERVED, weight=BOLD).next_to(pix.box, UP, buff=0.15).align_to(pix.box, LEFT)

        col = VGroup(*[T(t, 16, TEXT) for t in n["lines"]]).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        col[3].set_color(GOLD)
        col[4].set_color(GOLD).shift(UP * 0.18)
        col.move_to([0, 0.6, 0]).align_to([0.45, 0, 0], LEFT)

        self.play(Create(pix), Create(grid), run_time=1.0)
        self.play(FadeIn(star), FadeIn(lab_pix), FadeIn(col[0]), FadeIn(col[1]), run_time=0.7)
        self.add(ghost)
        self.bring_to_front(grid, star)
        self.play(ApplyPointwiseFunction(wcs_map, grid), ReplacementTransform(pix, skyp),
                  FadeIn(col[2]), FadeIn(col[3]), FadeIn(col[4]), run_time=2.0)
        lab_sky = T(n["sky_text"], 18, OBSERVED, weight=BOLD).next_to(star, DOWN + RIGHT, buff=0.1)
        lab_sky.add_background_rectangle(color="#0A1630", opacity=0.85, buff=0.05)
        sky_note = T("faint: the pixel grid before the transform", 14, MUTED)
        sky_note.next_to(col, DOWN, buff=0.45).align_to(col, LEFT)
        self.play(FadeOut(lab_pix), FadeIn(lab_sky), Indicate(star, color=GOLD), FadeIn(sky_note), run_time=0.9)
        self.wait(1.5)
