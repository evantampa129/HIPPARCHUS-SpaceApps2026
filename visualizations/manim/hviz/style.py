"""Shared look for every HIPPARCHUS scene: colours, type, frame labels, source line.

We keep the palette small and colour-blind safe (blue vs orange/gold, never
red vs green), and we never rely on colour alone: every state also has a word.
"""

from manim import (DOWN, LEFT, RIGHT, UP, UL, UR, DL, DR, BOLD, NORMAL,
                   RoundedRectangle, Scene, Text, VGroup, Square, Rectangle,
                   interpolate_color, ManimColor)

BG = "#0A1630"        # deep navy
PANEL = "#13254A"
GRID = "#2A4170"
BLUE = "#56B4E9"      # Okabe-Ito sky blue
GOLD = "#F2C14E"
ORANGE = "#E69F00"    # refused / failing, always with a word next to it
VERMIL = "#E07A5F"
TEXT = "#EAF0FA"
MUTED = "#9FB0CC"
GREY = "#5D6B82"      # flagged / unusable

FONT = "Inter"

SOURCE_SPHEREX = "SPHEREx DR1/QR3, NASA/IPAC IRSA · HIPPARCHUS"
SOURCE_HORIZONS = "SPHEREx DR1, NASA/IPAC IRSA · JPL Horizons (observer = SPHEREx) · HIPPARCHUS"
SOURCE_CONCEPT = "Illustration by HIPPARCHUS · no archive data shown"

LABELS = ("DATA-DRIVEN", "SIMULATED", "CONCEPTUAL", "HISTORICAL ILLUSTRATION", "EXPERIMENTAL")
_LABEL_COLOUR = {"DATA-DRIVEN": BLUE, "SIMULATED": GOLD, "CONCEPTUAL": GOLD,
                 "HISTORICAL ILLUSTRATION": MUTED, "EXPERIMENTAL": ORANGE}


def T(text, size=24, color=TEXT, weight=NORMAL, **kw):
    """Text in our sans font. Sizes are Manim font sizes at the 1080p frame."""
    return Text(text, font=FONT, font_size=size, color=color, weight=weight, **kw)


def badge(label, size=18):
    """Small outlined tag, e.g. DATA-DRIVEN. Colour follows the label type."""
    c = _LABEL_COLOUR.get(label, MUTED)
    t = T(label, size=size, color=c, weight=BOLD)
    box = RoundedRectangle(corner_radius=0.08, width=t.width + 0.3, height=t.height + 0.18,
                           stroke_color=c, stroke_width=2, fill_color=BG, fill_opacity=0.85)
    g = VGroup(box, t.move_to(box))
    g.label_text = label
    return g


def chrome(scene_id, title, labels, source):
    """Title top-left, label badges top-right, source line bottom-left, team bottom-right."""
    head = VGroup(T(scene_id, 20, GOLD, BOLD), T(title, 24, TEXT, BOLD)).arrange(RIGHT, buff=0.25)
    head.to_corner(UL, buff=0.35)
    tags = VGroup(*[badge(l) for l in labels]).arrange(RIGHT, buff=0.15).to_corner(UR, buff=0.32)
    src = T(source, 15, MUTED).to_corner(DL, buff=0.3)
    team = T("HIPPARCHUS · AETHENOVA", 15, MUTED).to_corner(DR, buff=0.3)
    return VGroup(head, tags, src, team)


class HScene(Scene):
    """Base scene: navy background and a frame chrome that stays on every frame."""

    SCENE_ID = "M00"
    TITLE = ""
    LABELS = ("DATA-DRIVEN",)
    SOURCE = SOURCE_SPHEREX

    def setup(self):
        self.camera.background_color = BG
        self.chrome = chrome(self.SCENE_ID, self.TITLE, self.LABELS, self.SOURCE)
        # Foreground, so nothing we animate can ever cover the labels.
        self.add_foreground_mobjects(self.chrome)


# ---------- colour maps (no matplotlib dependency) ----------

_SEQ = ["#0A1630", "#1D3F7A", "#2F7FC1", "#56B4E9", "#F2C14E", "#FFF3C4"]
_DIV = ["#56B4E9", "#2F5E9E", "#13254A", "#B07A1E", "#F2C14E"]  # blue - navy - gold


def _ramp(stops, x):
    x = min(max(float(x), 0.0), 1.0) * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    return interpolate_color(ManimColor(stops[i]), ManimColor(stops[i + 1]), x - i)


def seq_color(x):
    return _ramp(_SEQ, x)


def div_color(x):
    """x in [-1, 1]: negative blue, positive gold."""
    return _ramp(_DIV, (x + 1) / 2)


def colorbar(cfn, lo_txt, hi_txt, title, width=0.22, height=2.4, n=40, diverging=False):
    cells = VGroup()
    for i in range(n):
        f = i / (n - 1)
        r = Rectangle(width=width, height=height / n, stroke_width=0,
                      fill_color=cfn(2 * f - 1 if diverging else f), fill_opacity=1)
        cells.add(r)
    cells.arrange(UP, buff=0)
    lo = T(lo_txt, 14, MUTED).next_to(cells, RIGHT, buff=0.08).align_to(cells, DOWN)
    hi = T(hi_txt, 14, MUTED).next_to(cells, RIGHT, buff=0.08).align_to(cells, UP)
    ttl = T(title, 14, MUTED).next_to(cells, UP, buff=0.12)
    return VGroup(cells, lo, hi, ttl)


def pixel_grid(arr, px=0.2, cfn=seq_color, norm=lambda v: v, bad=None, stroke=GRID):
    """One square per native pixel; None/NaN or flagged pixels are grey and hatched-free."""
    rows = len(arr)
    cols = len(arr[0])
    g = VGroup()
    for i in range(rows):
        for j in range(cols):
            v = arr[i][j]
            flagged = bad is not None and bad[i][j]
            if v is None or v != v or flagged:
                c, op = GREY, 1.0
            else:
                c, op = cfn(norm(v)), 1.0
            sq = Square(side_length=px, stroke_color=stroke, stroke_width=0.6,
                        fill_color=c, fill_opacity=op)
            # Row 0 of the image is the bottom (FITS convention), so y grows up.
            sq.move_to([(j - (cols - 1) / 2) * px, (i - (rows - 1) / 2) * px, 0])
            g.add(sq)
    g.shape = (rows, cols)
    g.px = px
    return g


def all_texts(mobjects):
    """Every Text string inside a list of mobjects (used by the tests)."""
    out = []
    for m in mobjects:
        for s in m.get_family():
            if isinstance(s, Text):
                out.append(s.text)
    return out
