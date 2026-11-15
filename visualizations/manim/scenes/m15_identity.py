"""M15: identity card: name, line, team and the four steps. Geometry only, no data, no logos."""

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Arc, Arrow, Circle, Create, Dot, FadeIn, LaggedStart, Line,
                   MoveAlongPath, VGroup, Write, linear)

import _path  # noqa: F401
from hviz.style import GEOMETRY, GOLD, GRID, MUTED, OBSERVED, SOURCE_CONCEPT, TEXT, HScene, T

EVIDENCE = []
STAGES = ("OBSERVE", "VERIFY", "CHALLENGE", "EXPLAIN")


def numbers():
    return {"name": "HIPPARCHUS", "line": "THE UNIVERSE IS NEVER STILL.", "team": "AETHENOVA", "stages": STAGES}


class M15Identity(HScene):
    SCENE_ID = "M15"
    TITLE = "Identity"
    LABELS = ("CONCEPTUAL",)
    SOURCE = SOURCE_CONCEPT

    def construct(self):
        n = numbers()
        c = np.array([0, 0.7, 0])
        orbit = Circle(radius=1.55, stroke_color=GRID, stroke_width=2).move_to(c)
        cross = VGroup(Line(c + LEFT * 1.9, c + RIGHT * 1.9, stroke_color=GRID, stroke_width=1),
                       Line(c + DOWN * 1.9, c + UP * 1.9, stroke_color=GRID, stroke_width=1))
        star = Dot(c, radius=0.07, color=GEOMETRY)
        body = Dot(orbit.point_from_proportion(0), radius=0.09, color=OBSERVED)
        trail = Arc(radius=1.55, start_angle=0, angle=0.0001, stroke_color=OBSERVED, stroke_width=3).move_arc_center_to(c)
        name = T(n["name"], 60, TEXT, weight=BOLD).move_to(c)
        name.add_background_rectangle(color="#0A1630", opacity=0.9, buff=0.12)
        line = T(n["line"], 24, GOLD, weight=BOLD).next_to(orbit, DOWN, buff=0.35)
        steps = VGroup()
        for i, s in enumerate(n["stages"]):
            steps.add(T(s, 20, TEXT, weight=BOLD))
            if i < len(n["stages"]) - 1:
                steps.add(T("→", 20, MUTED))
        steps.arrange(RIGHT, buff=0.3).next_to(line, DOWN, buff=0.4)
        team = T(n["team"], 18, MUTED, weight=BOLD).next_to(steps, DOWN, buff=0.35)

        # The small body keeps moving for the whole card: the sky is never still.
        self.add(trail, body)
        body.add_updater(lambda m, dt: m.move_to(orbit.point_from_proportion((self.renderer.time / 3.5 * 0.45) % 1)))
        trail.add_updater(lambda m: m.become(Arc(radius=1.55, start_angle=0,
                                                 angle=max(1e-4, 2 * np.pi * (self.renderer.time / 3.5 * 0.45) % (2 * np.pi)),
                                                 stroke_color=OBSERVED, stroke_width=3).move_arc_center_to(c)))
        self.play(Create(orbit), FadeIn(cross), FadeIn(star), FadeIn(name), run_time=0.8)
        self.play(Write(line), run_time=0.6)
        self.play(LaggedStart(*[FadeIn(s, shift=0.1 * UP) for s in steps], lag_ratio=0.25), run_time=0.9)
        self.play(FadeIn(team), run_time=0.4)
        self.wait(0.8)
