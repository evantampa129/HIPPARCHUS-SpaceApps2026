"""M09: Observation Compatibility Graph: epochs at (time, wavelength), edges = compared pairs."""

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Circle, Create, Dot, FadeIn, LaggedStart, Line, VGroup)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel, mjd_label
from hviz.style import BLUE, GOLD, GREY, INVALID, MUTED, TEXT, HScene, T

EVIDENCE = ["compat_check.json"]
ORDER = ("rw_aur", "barnard", "wise0855")


def numbers():
    c = D.compat()
    out = {}
    for tid in ORDER:
        g = c["graphs"][tid]
        s = g["summary"]
        out[tid] = {"nodes": g["nodes"], "edges": g["edges"], "summary": s,
                    "caption": f'{s["n_nodes"]} epochs · {s["n_usable"]} usable · {s["n_edges"]} edges of {s["n_pairs"]} pairs'}
    return out


class M09CompatGraph(HScene):
    SCENE_ID = "M09"
    TITLE = "Observation Compatibility Graph"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · compat_check.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        xs = [-4.45, 0.15, 4.75]
        for tid, x in zip(ORDER, xs):
            g = n[tid]
            t = [v["mjd"] for v in g["nodes"]]
            lam = [v["wavelength_um"] for v in g["nodes"]]
            tr = (min(t) - 15, max(t) + 15)
            lr = (min(lam) - 0.05 * (max(lam) - min(lam)), max(lam) + 0.05 * (max(lam) - min(lam)))
            ticks_t = [(v, mjd_label(v)) for v in np.linspace(tr[0] + 20, tr[1] - 20, 3)]
            ticks_l = [(v, f"{v:.2f}") for v in np.linspace(lr[0], lr[1], 5)[1:-1]]
            p = Panel(tr, lr, 3.4, 3.7, x_label="time (UTC)", y_label="λ at the star (µm)", x_ticks=ticks_t,
                      y_ticks=ticks_l, title=D.TARGET_NAMES[tid], size=13).move_to([x, 0.45, 0])
            pos = {v["id"]: p.c2p(v["mjd"], v["wavelength_um"]) for v in g["nodes"]}
            nodes = VGroup()
            for v in g["nodes"]:
                if v["usable"]:
                    nodes.add(Dot(pos[v["id"]], radius=0.05, color=BLUE))
                else:
                    # Flagged epochs stay in the graph, hollow and in the INVALID colour, with their reason in the data.
                    nodes.add(Circle(radius=0.045, stroke_color=INVALID, stroke_width=1.5).move_to(pos[v["id"]]))
            edges = VGroup(*[Line(pos[e["a"]], pos[e["b"]], stroke_color=GOLD, stroke_width=2.2) for e in g["edges"]])
            cap = T(g["caption"], 14, TEXT).next_to(p, DOWN, buff=0.15)
            self.play(FadeIn(p), LaggedStart(*[FadeIn(d) for d in nodes], lag_ratio=0.01), run_time=0.9)
            if len(edges):
                self.play(Create(edges), FadeIn(cap), run_time=0.7)
            else:
                none = T("no edges: every epoch flagged on the star", 15, INVALID).next_to(cap, DOWN, buff=0.1)
                self.play(FadeIn(cap), FadeIn(none), run_time=0.7)
        legend = VGroup(Dot(radius=0.06, color=BLUE), T("usable epoch", 15, TEXT),
                        Circle(radius=0.055, stroke_color=INVALID, stroke_width=1.5), T("flagged / unusable epoch", 15, TEXT),
                        Line([0, 0, 0], [0.4, 0, 0], stroke_color=GOLD, stroke_width=3),
                        T("compared pair (same detector, |Δλ| ≤ ½ channel)", 15, TEXT)).arrange(RIGHT, buff=0.15)
        legend.move_to([0, -2.95, 0])
        self.play(FadeIn(legend), run_time=0.5)
        self.wait(1.4)
