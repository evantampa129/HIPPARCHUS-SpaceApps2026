"""M05: Stability Fingerprint: every check behind 24/24, 18/24 and 34/34, cell by cell."""

from manim import (DOWN, LEFT, RIGHT, UP, BOLD, FadeIn, LaggedStart, Line, Rectangle, VGroup, Write)

import _path  # noqa: F401
from hviz import data as D
from hviz.style import BLUE, GOLD, GREY, MUTED, ORANGE, TEXT, HScene, T

EVIDENCE = ["robustness.json"]
CELL, GAP = 0.24, 0.04


def claim_cells(target, claim):
    """Ordered list of (group, holds) cells for one claim, rebuilt from the evidence."""
    cells = []
    complete = [s for s in target["stability"] if s["complete"]]
    for s in complete:
        cells.append(("settings", bool(s["claim_holds"][claim["claim"]])))
    held, n = claim["leave_one_pair_out"]
    # The file gives the count for leave-one-pair-out, not which pair failed; we draw holds first.
    cells += [("leave-one-pair-out", i < held) for i in range(n)]
    if claim["with_systematic_floor"] is not None:
        cells.append(("floor", bool(claim["with_systematic_floor"])))
    held, n = claim["wavelength_rule"]
    cells += [("λ rule", i < held) for i in range(n)]
    return cells


def numbers():
    r = D.robustness()
    rows = []
    for tid in ("rw_aur", "wise0855"):
        t = r["targets"][tid]
        for c in t["claims"]:
            cells = claim_cells(t, c)
            rows.append({"target": D.TARGET_NAMES[tid], "claim": c["claim"], "verdict": c["verdict"],
                         "n_checks": c["n_checks"], "n_holding": c["n_holding"], "cells": cells,
                         "score": f'{c["n_holding"]}/{c["n_checks"]}'})
    fails = sorted({f[0] for t in ("rw_aur", "wise0855") for c in r["targets"][t]["claims"]
                    for f in c["failing_settings"]})
    n_fail = sum(len(c["failing_settings"]) for t in ("rw_aur", "wise0855") for c in r["targets"][t]["claims"])
    fail_text = f"fails (all {n_fail}: " + ", ".join(f"{a:g} px" for a in fails) + " aperture)"
    return {"rows": rows, "rule": r["settings"]["rule"], "fail_text": fail_text,
            "tagline": "rule-based labels, not probabilities"}


class M05Fingerprint(HScene):
    SCENE_ID = "M05"
    TITLE = "Stability Fingerprint"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · robustness.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        x0, y = -6.3, 2.45
        all_rows = VGroup()
        for row in n["rows"]:
            head = T(f'{row["target"]}: "{row["claim"]}"', 17, TEXT).move_to([0, y, 0]).align_to([x0, 0, 0], LEFT)
            cells, groups = VGroup(), VGroup()
            prev = None
            x = x0
            for g, ok in row["cells"]:
                if prev is not None and g != prev:
                    x += 0.3  # small gap between check families
                r = Rectangle(width=CELL, height=CELL * 1.5, stroke_width=1, stroke_color="#0A1630",
                              fill_color=BLUE if ok else ORANGE, fill_opacity=1)
                r.move_to([x + CELL / 2, y - 0.5, 0])
                if not ok:
                    # A slash as well as the colour, so the failing cells read without colour vision.
                    r.add(Line(r.get_corner(DOWN + LEFT), r.get_corner(UP + RIGHT), stroke_color="#0A1630", stroke_width=2))
                cells.add(r)
                if g != prev:
                    groups.add(T(g, 12, MUTED).next_to(r, DOWN, buff=0.08).align_to(r, LEFT))
                prev = g
                x += CELL + GAP
            verdict_col = BLUE if row["verdict"] == "robust" else GOLD
            score = VGroup(T(row["score"], 26, TEXT, weight=BOLD), T(row["verdict"].upper(), 16, verdict_col, weight=BOLD))
            score.arrange(RIGHT, buff=0.2).next_to(cells, RIGHT, buff=0.4)
            self.play(FadeIn(head), run_time=0.3)
            self.play(LaggedStart(*[FadeIn(c) for c in cells], lag_ratio=0.04), FadeIn(groups), run_time=1.1)
            self.play(FadeIn(score), run_time=0.3)
            all_rows.add(head, cells, groups, score)
            y -= 1.5
        legend = VGroup(Rectangle(width=CELL, height=CELL, fill_color=BLUE, fill_opacity=1, stroke_width=0),
                        T("claim holds", 15, TEXT),
                        Rectangle(width=CELL, height=CELL, fill_color=ORANGE, fill_opacity=1, stroke_width=0),
                        T(n["fail_text"], 15, TEXT)).arrange(RIGHT, buff=0.15)
        legend.move_to([0, y + 0.2, 0]).align_to([x0, 0, 0], LEFT)
        tag = T(n["tagline"], 26, GOLD, weight=BOLD).next_to(legend, DOWN, buff=0.3).align_to(legend, LEFT)
        rule = T("robust = holds in every valid setting · sensitive = in at least half", 15, MUTED)
        rule.next_to(tag, RIGHT, buff=0.4).align_to(tag, DOWN)
        self.play(FadeIn(legend), Write(tag), FadeIn(rule), run_time=1.0)
        self.wait(1.4)
