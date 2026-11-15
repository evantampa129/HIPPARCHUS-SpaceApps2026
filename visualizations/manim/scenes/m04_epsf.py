"""M04: experimental ePSF fit on native pixels: data, model, residual, and an honest reduced chi2."""

import math

import numpy as np
from manim import DOWN, LEFT, RIGHT, UP, BOLD, FadeIn, LaggedStart, VGroup, Write

import _path  # noqa: F401
from hviz import data as D
from hviz.style import (BLUE, GOLD, MUTED, ORANGE, TEXT, HScene, T, badge, colorbar, div_color,
                        pixel_grid, seq_color)

EVIDENCE = ["epsf_check.json"]
PX = 0.36
RES_CLIP = 10.0  # colour scale for the residual, in sigma


def numbers():
    e = D.epsf()
    p = D.pixels()
    obs = p["obs_id"] if p else None
    rw = e["targets"]["rw_aur"]
    pub = e["diagnostics"]["variants"]["published"]["rw_aur"]
    best = e["diagnostics"]["variants"]["field_stars+sky_scale"]["rw_aur"]
    fit = rw["fits"][obs] if obs else None
    return {"obs_id": obs, "chi2_epoch": fit["chi2_red"] if fit else None, "dof": fit["dof"] if fit else None,
            "chi2_median": pub["chi2_red"]["median"], "n_epochs": pub["chi2_red"]["n"],
            "chi2_min": pub["chi2_red"]["min"], "chi2_max": pub["chi2_red"]["max"],
            "chi2_best_median": best["chi2_red"]["median"], "within_2pct": pub["within_2pct"],
            "n_ratios": pub["n_ratios"], "max_abs_ratio_dev": pub["max_abs_ratio_dev"],
            "lines": [f'χ²_red = {fit["chi2_red"]:.1f} on this epoch ({fit["dof"]} d.o.f.): the model does not describe these pixels to within the noise.' if fit else "",
                      f'All {pub["chi2_red"]["n"]} RW Aur epochs: median χ²_red {pub["chi2_red"]["median"]:.2f} (range {pub["chi2_red"]["min"]:.1f}–{pub["chi2_red"]["max"]:.1f}); '
                      f'{best["chi2_red"]["median"]:.1f} with Gaia field stars + measured sky scale.',
                      f'Still, flux ratios agree with the aperture: {pub["within_2pct"]}/{pub["n_ratios"]} within 2% '
                      f'(max {100*pub["max_abs_ratio_dev"]:.1f}%). Not used for any published number.']}


class M04EPSF(HScene):
    SCENE_ID = "M04"
    TITLE = "Second measurement: ePSF fit on native pixels"
    LABELS = ("DATA-DRIVEN", "EXPERIMENTAL")
    SOURCE = "SPHEREx DR1, NASA/IPAC IRSA · SPHEREx ePSF calibration · epsf_check.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        p = D.pixels()
        ep = p["epsf"]
        data = np.array([[np.nan if v is None else v for v in r] for r in ep["data"]])
        vmax = np.nanmax(data)
        s = 0.01 * vmax
        norm = lambda v: math.asinh(max(v, 0) / s) / math.asinh(vmax / s)  # noqa: E731
        g_data = pixel_grid(ep["data"], PX, seq_color, norm)
        g_model = pixel_grid(ep["model"], PX, seq_color, norm)
        g_res = pixel_grid(ep["residual_sigma"], PX, div_color, lambda v: max(-1, min(1, v / RES_CLIP)))
        panels = VGroup(g_data, g_model, g_res).arrange(RIGHT, buff=0.9).move_to([0.15, 0.75, 0])
        heads = VGroup(T("DATA", 18, TEXT, weight=BOLD), T("ePSF MODEL", 18, TEXT, weight=BOLD),
                       T("RESIDUAL (data − model) / σ", 18, TEXT, weight=BOLD))
        for h, g in zip(heads, panels):
            h.next_to(g, UP, buff=0.15)
        subs = VGroup(T(f'{p["obs_id"]}, 9 × 9 native px', 14, MUTED),
                      T("amplitude + constant sky, no reprojection", 14, MUTED),
                      T(f"colour clipped at ±{RES_CLIP:g}σ", 14, MUTED))
        for t_, g in zip(subs, panels):
            t_.next_to(g, DOWN, buff=0.12)
        cb1 = colorbar(seq_color, "0", f"{vmax:.0f}", "MJy/sr", height=2.2).next_to(g_data, LEFT, buff=0.35)
        cb2 = colorbar(div_color, f"−{RES_CLIP:g}σ", f"+{RES_CLIP:g}σ", "", height=2.2, diverging=True)
        cb2.next_to(g_res, RIGHT, buff=0.2)

        self.play(FadeIn(heads[0]), FadeIn(subs[0]), FadeIn(cb1),
                  LaggedStart(*[FadeIn(q) for q in g_data], lag_ratio=0.01), run_time=1.0)
        self.play(FadeIn(heads[1]), FadeIn(subs[1]),
                  LaggedStart(*[FadeIn(q) for q in g_model], lag_ratio=0.01), run_time=1.0)
        self.play(FadeIn(heads[2]), FadeIn(subs[2]), FadeIn(cb2),
                  LaggedStart(*[FadeIn(q) for q in g_res], lag_ratio=0.01), run_time=1.0)
        lines = VGroup(T(n["lines"][0], 18, ORANGE, weight=BOLD), T(n["lines"][1], 16, TEXT),
                       T(n["lines"][2], 16, TEXT)).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        lines.move_to([0, -2.45, 0])
        for l in lines:
            self.play(FadeIn(l), run_time=0.5)
        self.wait(1.6)
