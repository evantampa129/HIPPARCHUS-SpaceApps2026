"""M02: SPHEREx channel response at two wavelengths, their overlap, and our pair rule."""

import math

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, UR, BOLD, Create, FadeIn, Polygon, VGroup, VMobject,
                   DashedVMobject, Line, Write, Transform, ReplacementTransform)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel
from hviz.style import BLUE, GOLD, GREY, INVALID, MUTED, TEXT, HScene, T, badge

EVIDENCE = ["compat_check.json"]
LABELS = ("DATA-DRIVEN",)
MODEL_TAG = "MODEL (top-hat / Gaussian surrogate)"


def numbers():
    c = D.compat()
    g = c["graphs"]["rw_aur"]
    nodes = {n["id"]: n for n in g["nodes"]}
    # Compatible example: the published RW Aur pair with the least overlap (the hardest case that passed).
    e = min(g["edges"], key=lambda e: e["overlap_tophat"])
    good = (nodes[e["a"]], nodes[e["b"]], e)
    # Incompatible example: of the usable pairs refused only for wavelength, the one closest to passing.
    usable = [n for n in g["nodes"] if n["usable"]]
    best = None
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            if abs(a["mjd"] - b["mjd"]) <= 0.5:
                continue  # same visit: never compared, not a wavelength refusal
            dl = abs(a["wavelength_um"] - b["wavelength_um"])
            if dl <= 0.5 * min(a["bandwidth_um"], b["bandwidth_um"]):
                continue
            o = D.overlap(a["wavelength_um"], a["bandwidth_um"], b["wavelength_um"], b["bandwidth_um"], "tophat")
            if best is None or o > best[0]:
                best = (o, a, b)
    _, a, b = best
    bad = (a, b, {"dlambda_um": abs(a["wavelength_um"] - b["wavelength_um"]),
                  "overlap_tophat": D.overlap(a["wavelength_um"], a["bandwidth_um"], b["wavelength_um"], b["bandwidth_um"], "tophat"),
                  "overlap_gaussian": D.overlap(a["wavelength_um"], a["bandwidth_um"], b["wavelength_um"], b["bandwidth_um"], "gaussian")})

    def row(p, ok):
        a, b, e = p
        half = 0.5 * min(a["bandwidth_um"], b["bandwidth_um"])
        return {"a": a, "b": b, "dl_nm": e["dlambda_um"] * 1e3, "half_nm": half * 1e3,
                "top": e["overlap_tophat"], "gau": e["overlap_gaussian"], "ok": ok,
                "text": [f'Δλ = {e["dlambda_um"]*1e3:.1f} nm   (half channel = {half*1e3:.1f} nm)',
                         f'overlap {100*e["overlap_tophat"]:.1f}% top-hat · {100*e["overlap_gaussian"]:.1f}% Gaussian',
                         "COMPATIBLE: compared" if ok else "INCOMPATIBLE: refused"]}

    lim = c["overlap_at_rule_limit"]
    return {"limit_tophat": lim["tophat"], "limit_gauss": lim["gaussian"],
            "rule_text": f'Rule |Δλ| ≤ ½ channel  ⇔  overlap ≥ {100*lim["tophat"]:.0f}% (top-hat) / {100*lim["gaussian"]:.1f}% (Gaussian)',
            "good": row(good, True), "bad": row(bad, False)}


def curves(panel, lam, w, colour):
    """Top-hat (solid) and Gaussian with FWHM = channel width (dashed), both unit area, scaled by w."""
    x0, x1 = panel.x_range
    top = VMobject().set_points_as_corners([panel.c2p(lam - w / 2, 0), panel.c2p(lam - w / 2, 1),
                                            panel.c2p(lam + w / 2, 1), panel.c2p(lam + w / 2, 0)])
    top.set_stroke(colour, 3)
    s = w / (2 * math.sqrt(2 * math.log(2)))
    xs = np.linspace(x0, x1, 200)
    g = VMobject().set_points_smoothly([panel.c2p(x, w * math.exp(-0.5 * ((x - lam) / s) ** 2) / (s * math.sqrt(2 * math.pi)))
                                        for x in xs])
    g = DashedVMobject(g.set_stroke(colour, 2), num_dashes=60)
    return VGroup(top, g)


def overlap_fill(panel, l1, w1, l2, w2):
    lo, hi = max(l1 - w1 / 2, l2 - w2 / 2), min(l1 + w1 / 2, l2 + w2 / 2)
    if hi <= lo:
        return VGroup()
    h = min(1.0, w1 / w2 if w1 < w2 else 1.0) * 1.0
    h = min(w1, w2) / max(w1, w2)  # on our w-scaled axis the lower top-hat sets the height
    return Polygon(panel.c2p(lo, 0), panel.c2p(lo, h), panel.c2p(hi, h), panel.c2p(hi, 0),
                   stroke_width=0, fill_color=TEXT, fill_opacity=0.28)


class M02Filters(HScene):
    SCENE_ID = "M02"
    TITLE = "Same star, two wavelengths: when can we compare?"
    LABELS = LABELS
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · compat_check.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        rule = T(n["rule_text"], 20, GOLD).move_to([0, 2.85, 0])
        self.play(FadeIn(rule), run_time=0.6)
        y = 1.15
        for key in ("good", "bad"):
            r = n[key]
            a, b = r["a"], r["b"]
            la, lb, wa, wb = a["wavelength_um"], b["wavelength_um"], a["bandwidth_um"], b["bandwidth_um"]
            mid, span = (la + lb) / 2, abs(la - lb) + 1.6 * max(wa, wb)
            ticks = [(v, f"{v:.3f}") for v in np.linspace(mid - span / 3, mid + span / 3, 3)]
            p = Panel((mid - span / 2, mid + span / 2), (0, 1.15), 6.4, 1.75, x_label="wavelength at the star (µm)",
                      x_ticks=ticks, y_ticks=[], size=14).move_to([-2.6, y, 0])
            ca, cb = curves(p, la, wa, BLUE), curves(p, lb, wb, GOLD)
            fill = overlap_fill(p, la, wa, lb, wb)
            la_t = T(f'{a["id"]}  λ = {la:.4f} µm', 14, BLUE)
            lb_t = T(f'{b["id"]}  λ = {lb:.4f} µm', 14, GOLD)
            leg = VGroup(la_t, lb_t).arrange(DOWN, aligned_edge=LEFT, buff=0.05)
            leg.next_to(p.box, RIGHT, buff=0.3).align_to(p.box, UP)
            col = BLUE if r["ok"] else INVALID
            txt = VGroup(*[T(s, 16, TEXT) for s in r["text"][:2]],
                         T(r["text"][2], 19, col, weight=BOLD)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
            txt.next_to(leg, DOWN, buff=0.22, aligned_edge=LEFT)
            self.play(Create(p), run_time=0.4)
            self.play(Create(ca), run_time=0.5)
            self.play(Create(cb), FadeIn(leg), run_time=0.5)
            self.play(FadeIn(fill), FadeIn(txt), run_time=0.6)
            y -= 2.85
        tag = badge(MODEL_TAG).move_to([-2.6, -3.25, 0])
        note = T("solid: top-hat · dashed: Gaussian, FWHM = channel width", 14, MUTED).next_to(tag, RIGHT, buff=0.3)
        self.play(FadeIn(tag), FadeIn(note), run_time=0.4)
        self.wait(1.4)
