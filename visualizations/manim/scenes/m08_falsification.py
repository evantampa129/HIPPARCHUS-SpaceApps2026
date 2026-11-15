"""M08: OBSERVE -> VERIFY -> CHALLENGE -> EXPLAIN for a refusal (Barnard) and a supported change (RW Aur)."""

from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Arrow, FadeIn, GrowArrow, Line, RoundedRectangle,
                   VGroup, Write)

import _path  # noqa: F401
from hviz import data as D
from hviz.style import BLUE, GOLD, GREY, INVALID, MUTED, PANEL, TEXT, HScene, T

EVIDENCE = ["barnard_spherex-d6.json", "rw_aur_spherex-d1.json", "robustness.json", "epsf_check.json",
            "compat_check.json"]
STAGES = ("OBSERVE", "VERIFY", "CHALLENGE", "EXPLAIN")


def numbers():
    b, r = D.target("barnard"), D.target("rw_aur")
    rob = D.robustness()["targets"]["rw_aur"]
    eps = D.epsf()["diagnostics"]["variants"]["published"]["rw_aur"]
    npairs = D.compat()["targets"]["rw_aur"]["graph_summary"]["n_pairs"]
    flagged_b = sum(any(i["code"] == "flagged_pixels" for i in e["issues"]) for e in b["epochs"])
    top = max(r["comparisons"], key=lambda c: c["flux_ratio"])
    rp = next(p for p in rob["pairs"] if (p["a"], p["b"]) == (top["a"], top["b"]))
    c1 = rob["claims"][0]
    return {
        "barnard": {"n": b["n_epochs"], "usable": b["n_usable"], "flagged": flagged_b,
                    "cells": [f'{b["n_epochs"]} epochs\n(detector D6)',
                              f'{b["n_usable"]}/{b["n_epochs"]} usable\nflags on the star\nin {flagged_b}/{b["n_epochs"]}',
                              "not run:\nnothing left to test",
                              f'COMPARISON REFUSED\n{b["n_usable"]}/{b["n_epochs"]} usable epochs']},
        "rw_aur": {"n": r["n_epochs"], "usable": r["n_usable"], "pairs": len(r["comparisons"]), "n_pairs": npairs,
                   "ratio": top["flux_ratio"], "sig": top["significance"], "sig_floor": rp["sig_with_systematics"],
                   "floor": rob["systematic_floor"], "lambda": top["lambda_a_um"],
                   "cells": [f'{r["n_epochs"]} epochs\n(detector D1)',
                             f'{r["n_usable"]} usable epochs\n{len(r["comparisons"])}/{npairs} pairs pass',
                             f'{c1["n_holding"]}/{c1["n_checks"]} settings hold\nePSF: {eps["within_2pct"]}/{eps["n_ratios"]} within 2%',
                             f'SUPPORTED CHANGE\n×{top["flux_ratio"]:.2f} at {top["lambda_a_um"]:.2f} µm\n'
                             f'{top["significance"]:.0f}σ formal · ≈{rp["sig_with_systematics"]:.0f}σ with\n'
                             f'{100*rob["systematic_floor"]:.1f}% calibration floor']},
    }


def cell(text, colour, w=2.7, h=1.55, dim=False):
    lines = text.split("\n")
    txt = VGroup(*[T(l, 15, TEXT if not dim else MUTED, weight=BOLD if i == 0 and colour != TEXT else "NORMAL")
                   for i, l in enumerate(lines)]).arrange(DOWN, buff=0.06)
    box = RoundedRectangle(corner_radius=0.12, width=w, height=h, stroke_color=colour, stroke_width=2,
                           fill_color=PANEL, fill_opacity=1)
    return VGroup(box, txt.move_to(box))


class M08Falsification(HScene):
    SCENE_ID = "M08"
    TITLE = "Observe → Verify → Challenge → Explain"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · Barnard + RW Aur evidence, robustness, ePSF · HIPPARCHUS"

    def construct(self):
        n = numbers()
        xs = [-4.55, -1.35, 1.85, 5.05]
        heads = VGroup(*[T(s, 20, GOLD, weight=BOLD).move_to([x, 2.6, 0]) for s, x in zip(STAGES, xs)])
        arrows_h = VGroup(*[Arrow(heads[i].get_right(), heads[i + 1].get_left(), buff=0.25, color=GOLD, stroke_width=3,
                                  max_tip_length_to_length_ratio=0.25) for i in range(3)])
        self.play(FadeIn(heads), *[GrowArrow(a) for a in arrows_h], run_time=0.8)

        for key, y, name, colours in (("barnard", 1.0, "Barnard's Star", [BLUE, INVALID, GREY, INVALID]),
                                      ("rw_aur", -1.55, "RW Aur", [BLUE, BLUE, BLUE, BLUE])):
            hh = 1.55 if key == "barnard" else 1.75
            lab = T(name, 18, TEXT, weight=BOLD).move_to([-6.45, y + hh / 2 + 0.22, 0]).align_to([-6.0, 0, 0], LEFT)
            self.play(FadeIn(lab), run_time=0.25)
            prev = None
            for i, (x, txt, col) in enumerate(zip(xs, n[key]["cells"], colours)):
                c = cell(txt, col, h=hh, dim=(col == GREY)).move_to([x, y, 0])
                anims = [FadeIn(c)]
                if prev is not None:
                    a = Arrow(prev.get_right(), c.get_left(), buff=0.05, stroke_width=3,
                              color=GREY if col == GREY else TEXT, max_tip_length_to_length_ratio=0.3)
                    anims.append(GrowArrow(a))
                self.play(*anims, run_time=0.45)
                prev = c
        foot = T("The same pipeline either refuses a comparison or measures a change, and says why.", 16, MUTED)
        foot.move_to([0, -2.95, 0])
        self.play(FadeIn(foot), run_time=0.4)
        self.wait(1.5)
