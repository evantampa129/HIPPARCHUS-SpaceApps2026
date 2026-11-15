"""M06: (216) Kleopatra in real SPHEREx exposures against JPL Horizons computed from SPHEREx."""

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, UL, BOLD, Arrow, Circle, Create, Dot, FadeIn, GrowArrow,
                   LaggedStart, Line, VGroup, VMobject, DashedVMobject)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel, mjd_label
from hviz.style import BLUE, GOLD, GREY, MUTED, TEXT, HScene, T

EVIDENCE = ["motion_check.json"]
RESID_SCALE = 60  # residual arrows are drawn this many times longer than they are


def to_plane(ra, dec, ra0, dec0):
    """Gnomonic projection in arcsec, same as backend/hipparchus/motion.py."""
    ra, dec, ra0, dec0 = (np.radians(np.asarray(v, float)) for v in (ra, dec, ra0, dec0))
    c = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / c
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / c
    return np.degrees(xi) * 3600.0, np.degrees(eta) * 3600.0


def numbers():
    m = D.motion()
    f = m["field"]
    ex = sorted([e for e in m["exposures"] if e.get("measured") and e["measured"].get("in_linked_track")],
                key=lambda e: e["mjd_mid"])
    t = np.array([e["mjd_mid"] for e in ex])
    mx, my = to_plane([e["measured"]["ra"] for e in ex], [e["measured"]["dec"] for e in ex], f["ra_center"], f["dec_center"])
    px, py = to_plane([e["horizons_spherex"]["ra"] for e in ex], [e["horizons_spherex"]["dec"] for e in ex],
                      f["ra_center"], f["dec_center"])
    err = np.array([e["measured"]["err_arcsec"] for e in ex])
    # Fitted motion: we refit the published order-2 weighted polynomial from the measured
    # points; the test checks that its rates equal the ones in motion_check.json.
    t_ref = m["fitted_motion"]["t_ref_mjd"]
    h = (t - t_ref) * 24.0
    cx = np.polyfit(h, mx, 2, w=1 / err)
    cy = np.polyfit(h, my, 2, w=1 / err)
    res = m["residuals_vs_horizons_spherex_arcsec"]["linked_track_members"]
    fm = m["fitted_motion"]
    visits = len(m["blind_search"]["tracks"][0:1]) and m["blind_search"]["tracks"][0]["n_visits"]
    return {"t": t, "measured": (mx, my), "predicted": (px, py), "cx": cx, "cy": cy, "t_ref": t_ref,
            "rate_fit": (float(cx[1]), float(cy[1])), "n": res["n"], "visits": visits,
            "rms_ra": res["rms_ra_cosdec"], "rms_dec": res["rms_dec"],
            "rate_sigma": (fm["rate_difference_arcsec_h"]["sigma_ra_cosdec"], fm["rate_difference_arcsec_h"]["sigma_dec"]),
            "resid": [(e["measured"]["resid_ra_cosdec_arcsec"], e["measured"]["resid_dec_arcsec"]) for e in ex],
            "lines": [f'{res["n"]} detections · {visits} visits · {fm["time_span_hours"]:.0f} h',
                      f'rms vs Horizons: {res["rms_ra_cosdec"]:.2f}″ (RA cos Dec), {res["rms_dec"]:.2f}″ (Dec)',
                      f'rates agree within {max(abs(v) for v in (fm["rate_difference_arcsec_h"]["sigma_ra_cosdec"], fm["rate_difference_arcsec_h"]["sigma_dec"])):.2f}σ'
                      f' ({fm["measured_rate_arcsec_h"]["total"]:.2f}″/h)'],
            "first": mjd_label(t[0], "%Y-%m-%d"), "last": mjd_label(t[-1], "%Y-%m-%d")}


class M06Kleopatra(HScene):
    SCENE_ID = "M06"
    TITLE = "Moving-object check: (216) Kleopatra vs JPL Horizons"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1, NASA/IPAC IRSA · JPL Horizons, observer = SPHEREx · motion_check.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        mx, my = n["measured"]
        px, py = n["predicted"]
        pad = 25
        xr = (max(mx.max(), px.max()) + pad, min(mx.min(), px.min()) - pad)  # east to the left
        yr = (min(my.min(), py.min()) - pad, max(my.max(), py.max()) + pad)
        H = 5.4
        W = H * abs(xr[0] - xr[1]) / (yr[1] - yr[0])  # equal arcsec scale on both axes
        p = Panel(xr, yr, W, H, x_label="ΔRA cos Dec (″)", y_label="ΔDec (″)",
                  x_ticks=[(v, f"{v:+.0f}" if v else "0") for v in (-50, 50) if xr[1] < v < xr[0]],
                  y_ticks=[(v, f"{v:+.0f}" if v else "0") for v in (-150, 0, 150) if yr[0] < v < yr[1]], size=13)
        p.move_to([-3.6, -0.05, 0])
        self.play(FadeIn(p), run_time=0.5)

        # Fitted motion (order-2 polynomial), white dashed.
        hh = np.linspace((n["t"][0] - n["t_ref"]) * 24, (n["t"][-1] - n["t_ref"]) * 24, 120)
        fit = VMobject().set_points_smoothly([p.c2p(np.polyval(n["cx"], h), np.polyval(n["cy"], h)) for h in hh])
        fit = DashedVMobject(fit.set_stroke(TEXT, 2), num_dashes=50)
        pred = VGroup(*[Circle(radius=0.07, stroke_color=GOLD, stroke_width=2).move_to(p.c2p(x, y))
                        for x, y in zip(px, py)])
        obs = VGroup(*[Dot(p.c2p(x, y), radius=0.035, color=BLUE) for x, y in zip(mx, my)])
        self.play(Create(fit), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(c) for c in pred], lag_ratio=0.05), run_time=1.0)
        self.play(LaggedStart(*[FadeIn(d) for d in obs], lag_ratio=0.05), run_time=1.0)

        # Residual arrows, exaggerated by RESID_SCALE, from prediction to measurement.
        u = p.w / abs(xr[0] - xr[1])  # scene units per arcsec
        arrows = VGroup()
        for (x, y), (rx, ry) in zip(zip(px, py), n["resid"]):
            a = p.c2p(x, y)
            # East is to the left on our plot, so +RA residual points left.
            b = a + np.array([-rx * RESID_SCALE * u, ry * RESID_SCALE * u, 0])
            arrows.add(Arrow(a, b, buff=0, stroke_width=2.5, color=GOLD, max_tip_length_to_length_ratio=0.3,
                             tip_length=0.08))
        bar_len = 0.5 * RESID_SCALE * u
        bar = Line([0, 0, 0], [bar_len, 0, 0], color=GOLD, stroke_width=4)
        # Two lines, so the caption stays inside the right column.
        bar_t = VGroup(T("arrows: Horizons → observed · bar = 0.5″", 14, GOLD),
                       T(f"(residuals ×{RESID_SCALE} for display)", 14, GOLD)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        sbar = VGroup(bar, bar_t.next_to(bar, RIGHT, buff=0.12)).move_to([2.6, -2.6, 0]).align_to([0.55, 0, 0], LEFT)
        self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.03), FadeIn(sbar), run_time=1.0)

        legend = VGroup(
            VGroup(Dot(radius=0.05, color=BLUE), T("observed: blind SPHEREx detections", 16, TEXT)).arrange(RIGHT, buff=0.15),
            VGroup(Circle(radius=0.07, stroke_color=GOLD, stroke_width=2), T("predicted: JPL Horizons as seen from SPHEREx", 16, TEXT)).arrange(RIGHT, buff=0.15),
            VGroup(DashedVMobject(Line([0, 0, 0], [0.35, 0, 0]).set_stroke(TEXT, 2), num_dashes=4),
                   T("fitted: order-2 polynomial through the observed points", 16, TEXT)).arrange(RIGHT, buff=0.15),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18).move_to([2.6, 1.6, 0]).align_to([0.55, 0, 0], LEFT)
        stats = VGroup(*[T(s, 18, TEXT if i else GOLD, weight=BOLD if i == 1 else "NORMAL") for i, s in enumerate(n["lines"])])
        stats.arrange(DOWN, aligned_edge=LEFT, buff=0.16).next_to(legend, DOWN, buff=0.5).align_to(legend, LEFT)
        when = T(f'{n["first"]} → {n["last"]} (mid-exposure times)', 15, MUTED).next_to(stats, DOWN, buff=0.3).align_to(legend, LEFT)
        note = T("Validation on one known asteroid. No new object is claimed.", 15, MUTED).next_to(when, DOWN, buff=0.12).align_to(legend, LEFT)
        self.play(FadeIn(legend), run_time=0.5)
        self.play(FadeIn(stats), FadeIn(when), FadeIn(note), run_time=0.6)
        self.wait(1.4)
