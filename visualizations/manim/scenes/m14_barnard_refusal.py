"""M14: Barnard's Star, exposure by exposure: every one flagged on the star, so the comparison is refused."""

import re
from collections import Counter

from manim import (DOWN, LEFT, RIGHT, UP, BOLD, FadeIn, Line, Rectangle, ValueTracker, VGroup, Write,
                   always_redraw, linear)

import _path  # noqa: F401
from hviz import data as D
from hviz.style import BG, INVALID, MUTED, OBSERVED, TEXT, HScene, T

EVIDENCE = ["barnard_spherex-d6.json"]
COLS, TILE, GAP = 15, 0.4, 0.07
PLANE = re.compile(r"([A-Z_]+) \((\d+) px\)")
OTHER = {"nan_pixels": "NaN pixels", "bad_variance": "bad variance"}


def reasons(e):
    """Reason words for one epoch: flag planes on the star's pixels, then other reject codes."""
    out = []
    for i in e["issues"]:
        if i["severity"] != "reject":
            continue
        if i["code"] == "flagged_pixels":
            out += [m.group(1) for m in PLANE.finditer(i["message"])]
        else:
            out.append(OTHER.get(i["code"], i["code"]))
    return out


def numbers():
    b = D.target("barnard")
    eps = sorted(b["epochs"], key=lambda e: e["mjd"])
    per = [reasons(e) for e in eps]
    tally = Counter(r for rs in per for r in set(rs))
    order = [k for k, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]
    usable = sum(e["usable"] for e in eps)
    return {"n": b["n_epochs"], "n_usable": b["n_usable"], "usable_counted": usable,
            "per_epoch": per, "tally": dict(tally), "order": order, "why": b["target"]["why"],
            "detector": b["detector"].replace("SPHEREx-", ""),
            "head": f'{b["n_epochs"]} exposures of Barnard\'s Star, detector {b["detector"].replace("SPHEREx-", "")}, in time order',
            "usable_text": f'usable: {b["n_usable"]}/{b["n_epochs"]}',
            "verdict": "COMPARISON REFUSED"}


class M14BarnardRefusal(HScene):
    SCENE_ID = "M14"
    TITLE = "Barnard's Star: why we refuse to compare"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · barnard_spherex-d6.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        k = ValueTracker(0)   # how many exposures have been checked so far
        x0, y0 = -6.35, 1.75
        tiles = VGroup()
        for i in range(n["n"]):
            r, c = divmod(i, COLS)
            box = Rectangle(width=TILE, height=TILE, stroke_color=BG, stroke_width=1.5,
                            fill_color=OBSERVED, fill_opacity=1)
            box.move_to([x0 + TILE / 2 + c * (TILE + GAP), y0 - r * (TILE + GAP), 0])
            slash = Line(box.get_corner(DOWN + LEFT), box.get_corner(UP + RIGHT), stroke_color=BG, stroke_width=2.5,
                         stroke_opacity=0)
            t = VGroup(box, slash)

            def upd(m, i=i):
                bad = k.get_value() > i and n["per_epoch"][i]
                m[0].set_fill(INVALID if bad else OBSERVED, 1)
                m[1].set_stroke(opacity=1 if bad else 0)
            t.add_updater(upd)
            tiles.add(t)
        head = T(n["head"], 17, TEXT, weight=BOLD).next_to(tiles, UP, buff=0.3).align_to(tiles, LEFT)
        leg = VGroup(Rectangle(width=0.26, height=0.26, fill_color=OBSERVED, fill_opacity=1, stroke_width=0),
                     T("OBSERVED exposure", 14, TEXT),
                     VGroup(Rectangle(width=0.26, height=0.26, fill_color=INVALID, fill_opacity=1, stroke_width=0),
                            Line([-0.13, -0.13, 0], [0.13, 0.13, 0], stroke_color=BG, stroke_width=2.5)),
                     T("INVALID: pixels on the star flagged", 14, TEXT)).arrange(RIGHT, buff=0.15)
        leg[2].shift(RIGHT * 0.25)
        leg[3].next_to(leg[2], RIGHT, buff=0.15)
        leg.next_to(tiles, DOWN, buff=0.35).align_to(tiles, LEFT)

        rx = 1.35
        rh = T("Reason words, exposures affected", 17, TEXT, weight=BOLD).move_to([0, 2.3, 0]).align_to([rx, 0, 0], LEFT)

        def table():
            done = int(min(k.get_value(), n["n"]))
            seen = Counter(r for rs in n["per_epoch"][:done] for r in set(rs))
            rows = VGroup()
            for name in n["order"]:
                rows.add(VGroup(T(name, 16, INVALID, weight=BOLD), T(f'{seen.get(name, 0)}/{n["n"]}', 16, TEXT)))
            for i, row in enumerate(rows):
                row[0].move_to([0, 1.45 - i * 0.4, 0]).align_to([rx, 0, 0], LEFT)
                row[1].move_to([0, 1.45 - i * 0.4, 0]).align_to([rx + 3.4, 0, 0], RIGHT)
            return rows

        tab = always_redraw(table)
        note = T("SPHEREx flag planes on the star's pixels, then our data checks", 13, MUTED)
        note.next_to(rh, DOWN, buff=0.1).align_to(rh, LEFT)

        self.play(FadeIn(tiles), FadeIn(head), FadeIn(leg[:2]), run_time=0.8)
        self.play(FadeIn(rh), FadeIn(note), FadeIn(tab), FadeIn(leg[2:]), run_time=0.5)
        self.play(k.animate.set_value(n["n"] + 0.5), run_time=3.0, rate_func=linear)
        # Freeze the final tallies as plain mobjects (also what the label test reads).
        k.set_value(n["n"] + 0.5)
        tiles.update()
        tab.clear_updaters()
        self.remove(tab)
        tab = table()
        self.add(tab)

        usable = T(n["usable_text"], 22, TEXT, weight=BOLD)
        verdict = T(n["verdict"], 34, INVALID, weight=BOLD)
        why = T(f'“{n["why"]}”', 15, MUTED)
        end = VGroup(usable, verdict).arrange(RIGHT, buff=0.5, aligned_edge=DOWN).move_to([0, -2.42, 0])
        why.next_to(end, DOWN, buff=0.22)
        self.play(FadeIn(usable), Write(verdict), run_time=0.9)
        self.play(FadeIn(why), run_time=0.5)
        self.wait(1.4)
