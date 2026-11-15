"""M03: aperture + sky-annulus photometry on real RW Aur pixels (r = 2 px, annulus 4-7 px)."""

import math

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Annulus, Circle, Create, Dot, FadeIn, LaggedStart,
                   VGroup, Write, Square, Indicate)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import mjd_label
from hviz.style import BLUE, GOLD, GREY, MUTED, TEXT, HScene, T, badge, colorbar, pixel_grid, seq_color

EVIDENCE = ["rw_aur_spherex-d1.json"]
PX = 0.25


def numbers():
    p = D.pixels()
    if p is None:
        return {"conceptual": True}
    ev = D.target("rw_aur")
    ep = {e["obs_id"]: e for e in ev["epochs"]}[p["obs_id"]]
    comp = next(c for c in ev["comparisons"] if c["a"] == p["obs_id"])
    sx, sy = p["star_xy_in_stamp"]
    n = len(p["stamp"])
    # We count the aperture pixels the same way the backend does (pixel centre within r).
    inside = [(i, j) for i in range(n) for j in range(n) if math.hypot(j - sx, i - sy) <= p["aperture_px"]]
    fa = comp["flux_a"]
    return {"conceptual": False, "obs_id": p["obs_id"], "date": ep["date_obs"][:10],
            "lambda_um": ep["wavelength_um"], "flux": fa["flux"], "flux_err": fa["flux_err"],
            "sky": fa["sky"], "n_pix": fa["n_pix"], "n_bad": p["photometry"]["n_bad"], "inside": inside, "n_sky": p["photometry"]["n_sky"],
            "aperture_px": p["aperture_px"], "annulus_px": p["annulus_px"],
            "lines": [f'{p["obs_id"]} · {ep["date_obs"][:10]} · λ = {ep["wavelength_um"]:.3f} µm',
                      f'aperture r = {p["aperture_px"]:g} px  →  {fa["n_pix"]} pixels',
                      f'sky annulus {p["annulus_px"][0]:g}–{p["annulus_px"][1]:g} px  →  {int(p["photometry"]["n_sky"])} pixels, median {fa["sky"]:.3f} MJy/sr',
                      f'flux = {fa["flux"]:.2f} ± {fa["flux_err"]:.2f}  (MJy/sr summed over pixels)']}


class M03Aperture(HScene):
    SCENE_ID = "M03"
    TITLE = "Aperture photometry on real SPHEREx pixels"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1, NASA/IPAC IRSA · cutout SHA-256 in rw_aur_spherex-d1.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        if n["conceptual"]:
            # Without the cached cutout we will not invent pixels.
            self.add(badge("CONCEPTUAL"), T("Real pixels not available on this machine", 24))
            self.wait(3)
            return
        p = D.pixels()
        stamp = np.array([[np.nan if v is None else v for v in row] for row in p["stamp"]])
        vmax = np.nanmax(stamp)
        s = 0.01 * vmax  # asinh stretch: the star core and the faint sky both stay visible
        norm = lambda v: math.asinh(max(v, 0) / s) / math.asinh(vmax / s)  # noqa: E731
        grid = pixel_grid(p["stamp"], PX, seq_color, norm, bad=p["stamp_bad"]).move_to([-3.0, -0.15, 0])
        rows, cols = grid.shape
        sx, sy = p["star_xy_in_stamp"]
        c0 = grid.get_center()
        star = c0 + np.array([(sx - (cols - 1) / 2) * PX, (sy - (rows - 1) / 2) * PX, 0])

        cap = T("21 × 21 native pixels (6.15″ each), zodiacal model removed", 15, MUTED).next_to(grid, UP, buff=0.15)
        cb = colorbar(seq_color, "0", f"{vmax:.1f}", "MJy/sr").next_to(grid, LEFT, buff=0.3)
        self.play(LaggedStart(*[FadeIn(q) for q in grid], lag_ratio=0.002), FadeIn(cap), FadeIn(cb), run_time=1.4)

        r_in, r_out = n["annulus_px"]
        ann = Annulus(inner_radius=r_in * PX, outer_radius=r_out * PX, fill_color=BLUE, fill_opacity=0.22,
                      stroke_width=0).move_to(star)
        ring = VGroup(Circle(radius=r_in * PX, stroke_color=BLUE, stroke_width=2.5).move_to(star),
                      Circle(radius=r_out * PX, stroke_color=BLUE, stroke_width=2.5).move_to(star))
        ap = Circle(radius=n["aperture_px"] * PX, stroke_color=GOLD, stroke_width=4).move_to(star)
        marks = VGroup(*[Square(PX * 0.86, stroke_color=GOLD, stroke_width=2).move_to(grid[i * cols + j])
                         for i, j in n["inside"]])

        lines = [T(t, 16, TEXT) for t in n["lines"]]
        lines[1].set_color(GOLD)
        lines[2].set_color(BLUE)
        lines[3] = T(n["lines"][3], 18, TEXT, weight=BOLD)
        col = VGroup(*lines).arrange(DOWN, aligned_edge=LEFT, buff=0.32).move_to([3.15, 0.3, 0])
        col.align_to([0.15, 0, 0], LEFT)
        self.play(FadeIn(lines[0]), run_time=0.4)
        self.play(Create(ap), FadeIn(marks), FadeIn(lines[1]), run_time=0.9)
        self.play(FadeIn(ann), Create(ring), FadeIn(lines[2]), run_time=0.9)
        self.play(FadeIn(lines[3]), Indicate(ap, color=GOLD, scale_factor=1.08), run_time=0.9)
        note = T("RW Aur A and B are 1.6″ apart: both fall in the aperture.", 15, MUTED)
        note.next_to(col, DOWN, buff=0.45).align_to(col, LEFT)
        grey = T("grey = flagged pixel, left out of the sky; none in the aperture", 15, MUTED).next_to(note, DOWN, buff=0.1).align_to(col, LEFT)
        self.play(FadeIn(note), FadeIn(grey), run_time=0.5)
        self.wait(1.3)
