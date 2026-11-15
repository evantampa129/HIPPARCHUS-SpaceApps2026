"""Small plotting kit built from Lines and Text only (no LaTeX needed)."""

import datetime as _dt

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, Line, Rectangle, VGroup, DashedLine)

from .style import GRID, MUTED, T, TEXT


def mjd_to_date(mjd):
    return _dt.datetime(1858, 11, 17) + _dt.timedelta(days=float(mjd))


def mjd_label(mjd, fmt="%Y-%m"):
    return mjd_to_date(mjd).strftime(fmt)


class Panel(VGroup):
    """A framed plotting area with linear axes, tick labels and axis titles."""

    def __init__(self, x_range, y_range, width, height, x_label="", y_label="",
                 x_ticks=(), y_ticks=(), title="", grid=True, size=15, **kw):
        super().__init__(**kw)
        self.x_range, self.y_range = x_range, y_range
        self.w, self.h = width, height
        self.box = Rectangle(width=width, height=height, stroke_color=GRID, stroke_width=1.5)
        self.add(self.box)
        for v, lab in x_ticks:
            p = self.c2p(v, y_range[0])
            if grid:
                self.add(Line(p, self.c2p(v, y_range[1]), stroke_color=GRID, stroke_width=0.6,
                              stroke_opacity=0.6))
            self.add(T(lab, size, MUTED).next_to(p, DOWN, buff=0.08))
        for v, lab in y_ticks:
            p = self.c2p(x_range[0], v)
            if grid:
                self.add(Line(p, self.c2p(x_range[1], v), stroke_color=GRID, stroke_width=0.6,
                              stroke_opacity=0.6))
            self.add(T(lab, size, MUTED).next_to(p, LEFT, buff=0.08))
        if x_label:
            self.xl = T(x_label, size + 1, MUTED).next_to(self.box, DOWN, buff=0.38)
            self.add(self.xl)
        if y_label:
            self.yl = T(y_label, size + 1, MUTED).rotate(np.pi / 2)
            self.yl.next_to(self.box, LEFT, buff=0.55 if y_ticks else 0.15)
            self.add(self.yl)
        if title:
            self.ttl = T(title, size + 3, TEXT).next_to(self.box, UP, buff=0.12).align_to(self.box, LEFT)
            self.add(self.ttl)

    def c2p(self, x, y):
        # We read the box position every time, so the panel can be moved after building.
        c = self.box.get_center()
        fx = (x - self.x_range[0]) / (self.x_range[1] - self.x_range[0]) - 0.5
        fy = (y - self.y_range[0]) / (self.y_range[1] - self.y_range[0]) - 0.5
        return np.array([c[0] + fx * self.w, c[1] + fy * self.h, 0.0])


def nice_ticks(lo, hi, n=4, fmt="{:.2f}"):
    vals = np.linspace(lo, hi, n + 2)[1:-1]
    return [(float(v), fmt.format(v)) for v in vals]
