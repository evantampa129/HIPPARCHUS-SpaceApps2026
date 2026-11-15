"""M11: the two real RW Aur exposures of the largest-ratio pair, their difference, and the question."""

import math

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, FadeIn, LaggedStart, VGroup, Write)

import _path  # noqa: F401
from hviz import data as D
from hviz.style import (GOLD, INVALID, MUTED, OBSERVED, TEXT, HScene, T, badge, colorbar,
                        div_color, pixel_grid, seq_color)

EVIDENCE = ["rw_aur_spherex-d1.json"]
PX = 0.17


def numbers():
    p = D.pair()
    ev = D.target("rw_aur")
    top = max(ev["comparisons"], key=lambda c: c["flux_ratio"])
    ep = {e["obs_id"]: e for e in ev["epochs"]}
    if p is None:
        return {"conceptual": True}
    ea, eb = ep[top["a"]], ep[top["b"]]
    fa, fb = top["flux_a"], top["flux_b"]
    n_bad = sum(map(sum, p["stamp_bad"]))
    return {"conceptual": False, "a": top["a"], "b": top["b"],
            "date_a": ea["date_obs"][:10], "date_b": eb["date_obs"][:10],
            "lambda_a": top["lambda_a_um"], "lambda_b": top["lambda_b_um"],
            "flux_a": fa["flux"], "flux_b": fb["flux"], "ratio": top["flux_ratio"], "dt_days": top["dt_days"],
            "n_bad": n_bad,
            "heads": [f'{ea["date_obs"][:10]} · λ = {top["lambda_a_um"]:.3f} µm',
                      f'{eb["date_obs"][:10]} · λ = {top["lambda_b_um"]:.3f} µm',
                      "difference: later − earlier"],
            "subs": [top["a"], f'{top["b"]} (on the earlier grid)', f'{n_bad} flagged pixels: INVALID, left out'],
            "line": f'aperture flux {fa["flux"]:.2f} → {fb["flux"]:.2f} MJy/sr · ratio ×{top["flux_ratio"]:.2f} · '
                    f'{top["dt_days"]:.0f} days apart',
            "stretch": f"both exposures: same asinh stretch, 0–{vmax_ab(p):.0f} MJy/sr · local sky removed",
            "question": "IS THIS CHANGE REAL?"}


def vmax_ab(p):
    return max(np.nanmax(arr(p["stamp_a"])), np.nanmax(arr(p["stamp_b"])))


def arr(rows):
    return np.array([[np.nan if v is None else v for v in r] for r in rows])


class M11ChangeReal(HScene):
    SCENE_ID = "M11"
    TITLE = "RW Aur: two exposures, one difference"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · cutout SHA-256 in rw_aur_spherex-d1.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        if n["conceptual"]:
            # Without the cached cutouts we will not invent pixels.
            self.add(badge("CONCEPTUAL"), T("Real pixels not available on this machine", 24))
            self.wait(3)
            return
        p = D.pair()
        a, b, d = arr(p["stamp_a"]), arr(p["stamp_b"]), arr(p["stamp_diff"])
        # One stretch for both epochs, so a brighter star looks brighter.
        vmax = max(np.nanmax(a), np.nanmax(b))
        s = 0.01 * vmax
        norm = lambda v: math.asinh(max(v, 0) / s) / math.asinh(vmax / s)  # noqa: E731
        dmax = np.nanmax(np.abs(d))
        dnorm = lambda v: math.copysign(math.asinh(abs(v) / (0.01 * dmax)) / math.asinh(100), v)  # noqa: E731

        xs, y0 = (-4.6, -0.6, 3.4), 0.15
        ga = pixel_grid(p["stamp_a"], PX, seq_color, norm).move_to([xs[0], y0, 0])
        gb = pixel_grid(p["stamp_b"], PX, seq_color, norm).move_to([xs[1], y0, 0])
        gd = pixel_grid(p["stamp_diff"], PX, lambda x: div_color(x), dnorm, bad=p["stamp_bad"],
                        bad_color=INVALID).move_to([xs[2], y0, 0])
        heads, subs = VGroup(), VGroup()
        for g, h, sub, col in zip((ga, gb, gd), n["heads"], n["subs"], (OBSERVED, OBSERVED, GOLD)):
            ht = T(h, 17, col, weight=BOLD).next_to(g, UP, buff=0.32)
            st = T(sub, 13, INVALID if "INVALID" in sub else MUTED).next_to(g, DOWN, buff=0.12)
            heads.add(ht)
            subs.add(st)
        minus = T("−", 40, TEXT).move_to([(xs[0] + xs[1]) / 2, y0, 0])
        equal = T("=", 40, TEXT).move_to([(xs[1] + xs[2]) / 2, y0, 0])

        self.play(LaggedStart(*[FadeIn(q) for q in ga], lag_ratio=0.001), FadeIn(heads[0]), FadeIn(subs[0]), run_time=1.0)
        self.play(LaggedStart(*[FadeIn(q) for q in gb], lag_ratio=0.001), FadeIn(heads[1]), FadeIn(subs[1]),
                  FadeIn(minus), run_time=1.0)
        self.play(LaggedStart(*[FadeIn(q) for q in gd], lag_ratio=0.001), FadeIn(heads[2]), FadeIn(subs[2]),
                  FadeIn(equal), run_time=1.0)
        cb2 = colorbar(div_color, f"−{dmax:.0f}", f"+{dmax:.0f}", "Δ MJy/sr", height=1.6, width=0.16, diverging=True)
        cb2.next_to(gd, RIGHT, buff=0.12).align_to(gd, DOWN)
        line = T(n["line"], 18, TEXT).move_to([0, -2.36, 0])
        stretch = T(n["stretch"], 13, MUTED).next_to(line, DOWN, buff=0.1)
        self.play(FadeIn(cb2), FadeIn(line), FadeIn(stretch), run_time=0.6)
        q = T(n["question"], 34, GOLD, weight=BOLD).move_to([0, -3.12, 0])
        self.play(Write(q), run_time=0.9)
        self.wait(1.6)
