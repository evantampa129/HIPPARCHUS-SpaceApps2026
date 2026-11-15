"""M13: the largest RW Aur change, first with formal errors only, then with the 12.5% calibration floor."""

import math

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Create, DashedLine, Dot, FadeIn, Line, ValueTracker, VGroup,
                   always_redraw, linear)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel
from hviz.style import GOLD, MUTED, OBSERVED, TEXT, UNCERTAINTY, HScene, T

EVIDENCE = ["rw_aur_spherex-d1.json", "robustness.json"]


def sigma_parts(n, floor):
    """Uncertainty of b - a when a fractional calibration error `floor` moves epoch b by floor * a.

    Same formula as backend/scripts/reproduce_robustness.py (sig_with_systematics).
    """
    bar_b = math.hypot(n["err_b"], floor * n["fa"])
    sig = math.hypot(n["err_a"], bar_b)
    return bar_b, sig, n["delta"] / sig


def numbers():
    ev = D.target("rw_aur")
    rob = D.robustness()["targets"]["rw_aur"]
    top = max(ev["comparisons"], key=lambda c: c["flux_ratio"])
    rp = next(p for p in rob["pairs"] if (p["a"], p["b"]) == (top["a"], top["b"]))
    ep = {e["obs_id"]: e for e in ev["epochs"]}
    fa, fb = top["flux_a"], top["flux_b"]
    floor = rob["systematic_floor"]
    n = {"a": top["a"], "b": top["b"], "date_a": ep[top["a"]]["date_obs"][:10], "date_b": ep[top["b"]]["date_obs"][:10],
         "fa": fa["flux"], "fb": fb["flux"], "err_a": fa["flux_err"], "err_b": fb["flux_err"],
         "delta": top["delta_flux"], "delta_err": top["delta_flux_err"], "ratio": top["flux_ratio"],
         "sig": top["significance"], "floor": floor, "sig_sys": rp["sig_with_systematics"],
         "threshold": ev["config"]["detection_sigma"]}
    bar_b, s_tot, sig_sys = sigma_parts(n, floor)
    n.update({"bar_b_sys": bar_b, "sigma_sys": s_tot, "sig_sys_recomputed": sig_sys})
    n["lines"] = [
        f'ratio b / a = ×{n["ratio"]:.2f}',
        f'Δ = b − a = {n["delta"]:.2f} MJy/sr',
        f'formal σ = √({n["err_a"]:.2f}² + {n["err_b"]:.2f}²) = {n["delta_err"]:.2f}',
        f'+ calibration floor {100 * floor:.1f}% (field-star scatter)',
        f'σ_cal = {floor:.3f} × a = {floor * n["fa"]:.2f}, carried by epoch b',
        f'σ = √({n["delta_err"]:.2f}² + {floor * n["fa"]:.2f}²) = {s_tot:.2f}',
    ]
    n["final"] = [f'{n["sig"]:.0f}σ formal → {n["sig_sys"]:.1f}σ with the floor:',
                  f'still above the {n["threshold"]:g}σ detection threshold']
    return n


class M13Uncertainty(HScene):
    SCENE_ID = "M13"
    TITLE = "RW Aur: how much of 175σ survives calibration?"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · rw_aur_spherex-d1.json · robustness.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        p = Panel((-0.55, 2.0), (0, 250), 4.6, 5.0, y_label="flux (MJy/sr summed over pixels)",
                  x_ticks=[(0, n["date_a"]), (1, n["date_b"])], y_ticks=[(v, f"{v}") for v in (50, 100, 150, 200)],
                  size=14)
        p.shift(np.array([-3.55, -0.1, 0]) - p.box.get_center())
        f = ValueTracker(0.0)   # calibration floor applied, 0 -> floor

        def bar(x, y, half, cap=0.13):
            lo, hi = p.c2p(x, y - half), p.c2p(x, y + half)
            return VGroup(Line(lo, hi, stroke_color=UNCERTAINTY, stroke_width=4),
                          Line(lo + LEFT * cap, lo + RIGHT * cap, stroke_color=UNCERTAINTY, stroke_width=3),
                          Line(hi + LEFT * cap, hi + RIGHT * cap, stroke_color=UNCERTAINTY, stroke_width=3))

        bar_a = bar(0, n["fa"], n["err_a"])
        bar_b = always_redraw(lambda: bar(1, n["fb"], sigma_parts(n, f.get_value())[0]))
        dot_a = Dot(p.c2p(0, n["fa"]), radius=0.075, color=OBSERVED)
        dot_b = Dot(p.c2p(1, n["fb"]), radius=0.075, color=OBSERVED)
        lab_a = T(f'a: {n["fa"]:.2f} ± {n["err_a"]:.2f}', 15, OBSERVED).next_to(dot_a, DOWN, buff=0.22)
        lab_b = T(f'b: {n["fb"]:.2f} ± {n["err_b"]:.2f}', 15, OBSERVED).next_to(dot_b, RIGHT, buff=0.25)
        level = DashedLine(p.c2p(-0.3, n["fa"]), p.c2p(1.25, n["fa"]), stroke_color=MUTED, stroke_width=1.5)
        level_t = T("no change", 13, MUTED).next_to(level, RIGHT, buff=0.08)

        def ruler():
            sig = sigma_parts(n, f.get_value())[1]
            k = int(n["delta"] // sig)
            ticks = VGroup(*[Line(p.c2p(0.5, n["fa"] + i * sig) + LEFT * 0.11, p.c2p(0.5, n["fa"] + i * sig) + RIGHT * 0.11,
                                  stroke_color=UNCERTAINTY, stroke_width=1.6) for i in range(k + 1)])
            return VGroup(Line(p.c2p(0.5, n["fa"]), p.c2p(0.5, n["fb"]), stroke_color=TEXT, stroke_width=1.5), ticks)

        rul = always_redraw(ruler)
        rul_t = T("one tick per σ", 13, UNCERTAINTY).next_to(p.c2p(0.5, n["fb"]), UP, buff=0.12)

        lines = [T(t, 17, TEXT) for t in n["lines"]]
        for i in (2, 3, 4, 5):
            lines[i].set_color(UNCERTAINTY)
        top = VGroup(*lines[:3]).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        bot = VGroup(*lines[3:]).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        col = VGroup(top, bot).arrange(DOWN, aligned_edge=LEFT, buff=0.95).move_to([0, 0.75, 0]).align_to([0.2, 0, 0], LEFT)

        def sig_text():
            s = sigma_parts(n, f.get_value())[2]
            g = VGroup(T("Δ / σ =", 22, TEXT), T(f"{s:.1f}σ", 34, GOLD, weight=BOLD),
                       T(f"floor {100 * f.get_value():.1f}%", 16, UNCERTAINTY)).arrange(RIGHT, buff=0.22, aligned_edge=DOWN)
            return g.move_to(top.get_bottom() + DOWN * 0.48).align_to(top, LEFT)

        sig = always_redraw(sig_text)

        self.play(Create(p), run_time=0.6)
        self.play(FadeIn(dot_a), FadeIn(dot_b), FadeIn(bar_a), FadeIn(bar_b), FadeIn(lab_a), FadeIn(lab_b),
                  Create(level), FadeIn(level_t), FadeIn(lines[0]), run_time=0.8)
        self.play(FadeIn(lines[1]), FadeIn(lines[2]), FadeIn(rul), FadeIn(rul_t), run_time=0.8)
        self.play(FadeIn(sig), run_time=0.5)
        self.wait(0.3)
        self.play(FadeIn(bot), run_time=0.6)
        self.play(f.animate.set_value(n["floor"]), run_time=2.4, rate_func=linear)
        fin = VGroup(*[T(t, 18, GOLD, weight=BOLD) for t in n["final"]]).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        fin.next_to(bot, DOWN, buff=0.4).align_to(col, LEFT)
        note = VGroup(T("Formal 1σ bars are thinner than the dots.", 13, MUTED),
                      T("The orange bar on b grows with the floor.", 13, MUTED)).arrange(DOWN, aligned_edge=LEFT, buff=0.05)
        note.next_to(fin, DOWN, buff=0.25).align_to(fin, LEFT)
        self.play(FadeIn(fin), FadeIn(note), run_time=0.6)
        self.wait(1.3)
