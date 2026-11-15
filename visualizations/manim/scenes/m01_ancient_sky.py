"""M01: from a schematic ancient star chart to the celestial coordinate grid."""

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Circle, Create, Dot, FadeIn, FadeOut,
                   LaggedStart, Line, VGroup, VMobject, Write, DashedVMobject, GrowFromCenter)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel
from hviz.style import BLUE, GOLD, GREY, GRID, MUTED, TEXT, HScene, T, badge

EVIDENCE = ["rw_aur_spherex-d1.json", "barnard_spherex-d6.json", "wise0855_spherex-d6.json"]
LABELS = ("CONCEPTUAL",)
OBLIQUITY_DEG = 23.44  # the ecliptic tilt, the only astronomical constant we draw


def numbers():
    out = {}
    for tid in ("rw_aur", "barnard", "wise0855"):
        t = D.target(tid)
        out[tid] = {"ra": t["ra"], "dec": t["dec"],
                    "text": f'{D.TARGET_NAMES[tid]}  RA {t["ra"]:.3f}°  Dec {t["dec"]:+.3f}°'}
    return out


def sphere_curve(points3, centre, r, tilt):
    """Orthographic view of a curve on the unit sphere; only the near side is drawn."""
    c, s = np.cos(tilt), np.sin(tilt)
    segs, cur = VGroup(), []
    for x, y, z in points3:
        # We tilt the pole towards the viewer, then look along -x.
        y2, z2 = y, z * c - x * s
        depth = x * c + z * s
        if depth >= 0:
            cur.append([centre[0] + r * y2, centre[1] + r * z2, 0])
        elif len(cur) > 1:
            segs.add(VMobject().set_points_smoothly(cur)); cur = []
        else:
            cur = []
    if len(cur) > 1:
        segs.add(VMobject().set_points_smoothly(cur))
    return segs


def radec_vec(ra, dec):
    return np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)


class M01AncientSky(HScene):
    SCENE_ID = "M01"
    TITLE = "From the ancient sky to a coordinate grid"
    LABELS = LABELS
    SOURCE = "Geometry and schematic chart by HIPPARCHUS · target RA/Dec from submission/evidence"

    def construct(self):
        nums = numbers()
        centre, R, tilt = np.array([-3.7, 0.3, 0]), 2.3, np.radians(35)
        rng = np.random.default_rng(129)  # a fixed seed: the same schematic every render

        # 1. Schematic star chart (illustration only, not a reproduction of any real chart).
        dome = Circle(radius=R, stroke_color=MUTED, stroke_width=2).move_to(centre)
        stars = VGroup()
        for _ in range(70):
            a, rr = rng.uniform(0, 2 * np.pi), R * np.sqrt(rng.uniform(0, 0.92))
            stars.add(Dot(centre + rr * np.array([np.cos(a), np.sin(a), 0]),
                          radius=rng.choice([0.018, 0.028, 0.04]), color=TEXT))
        figure = VGroup()
        for idx in ([0, 5, 9, 14], [20, 22, 27, 31, 20], [40, 44, 47]):
            pts = [stars[i].get_center() for i in idx]
            figure.add(*[Line(p, q, stroke_color=GOLD, stroke_width=1.5, stroke_opacity=0.7)
                         for p, q in zip(pts, pts[1:])])
        hist = badge("HISTORICAL ILLUSTRATION").next_to(dome, UP, buff=0.12)
        hist_note = T("schematic chart, not a copy of any real catalogue", 14, MUTED).next_to(dome, DOWN, buff=0.12)
        self.play(Create(dome), LaggedStart(*[FadeIn(s) for s in stars], lag_ratio=0.02),
                  FadeIn(hist), FadeIn(hist_note), run_time=1.4)
        self.play(Create(figure), run_time=0.7)

        # 2. The same sphere with a coordinate grid drawn from geometry.
        grid = VGroup()
        t = np.linspace(0, 2 * np.pi, 160)
        for dec in np.radians([-60, -30, 30, 60]):
            grid.add(sphere_curve([radec_vec(a, dec) for a in t], centre, R, tilt))
        for ra in np.radians(np.arange(0, 180, 30)):
            grid.add(sphere_curve([radec_vec(ra, d) for d in t], centre, R, tilt))
        grid.set_stroke(BLUE, 1.2, 0.55)
        equator = sphere_curve([radec_vec(a, 0) for a in t], centre, R, tilt).set_stroke(GOLD, 2.5)
        eps = np.radians(OBLIQUITY_DEG)
        ecl = []
        for a in t:  # ecliptic: the equator rotated by the obliquity about the x axis
            x, y, z = np.cos(a), np.sin(a), 0
            ecl.append((x, y * np.cos(eps) - z * np.sin(eps), y * np.sin(eps) + z * np.cos(eps)))
        ecliptic = sphere_curve(ecl, centre, R, tilt).set_stroke(TEXT, 1.6, 0.8)
        ecl_dash = VGroup(*[DashedVMobject(m, num_dashes=40) for m in ecliptic])
        key = VGroup(T("celestial equator", 15, GOLD), T(f"ecliptic, tilted {OBLIQUITY_DEG}°", 15, TEXT),
                     T("RA / Dec grid", 15, BLUE)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        key.next_to(dome, DOWN, buff=0.12)
        self.play(FadeOut(figure), FadeOut(hist_note), stars.animate.set_opacity(0.35),
                  Create(grid), Create(equator), Create(ecl_dash), FadeIn(key), run_time=1.6)

        # 3. Unrolled: RA/Dec chart with our three real targets.
        p = Panel((360, 0), (-90, 90), 5.6, 3.6, x_label="right ascension (deg)", y_label="declination (deg)",
                  x_ticks=[(v, f"{v}") for v in (300, 240, 180, 120, 60)],
                  y_ticks=[(v, f"{v:+d}".replace("-", "−") if v else "0") for v in (-60, -30, 0, 30, 60)], title="Equatorial grid (RA, Dec)")
        p.move_to([3.2, 0.75, 0])
        p.add(Line(p.c2p(360, 0), p.c2p(0, 0), stroke_color=GOLD, stroke_width=2))
        self.play(FadeIn(p), run_time=0.8)
        marks, labs = VGroup(), VGroup()
        for i, tid in enumerate(("rw_aur", "barnard", "wise0855")):
            n = nums[tid]
            d = Dot(p.c2p(n["ra"], n["dec"]), radius=0.07, color=GOLD)
            marks.add(d)
            labs.add(T(n["text"], 16, TEXT))
        labs.arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(p, DOWN, buff=0.7).align_to(p, LEFT)
        # Names go on the side away from the equator line, so they never sit on it.
        names = VGroup(*[T(D.TARGET_NAMES[k], 14, GOLD).next_to(m, UP if nums[k]["dec"] > 0 else DOWN, buff=0.06)
                         for k, m in zip(("rw_aur", "barnard", "wise0855"), marks)])
        self.play(LaggedStart(*[GrowFromCenter(m) for m in marks], lag_ratio=0.2),
                  FadeIn(names), FadeIn(labs), run_time=1.0)
        self.wait(1.3)
