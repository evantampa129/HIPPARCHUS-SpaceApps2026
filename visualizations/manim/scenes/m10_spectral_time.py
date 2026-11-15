"""M10: per-epoch wavelength vs time, with flux only where the evidence has a per-epoch flux."""

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, BOLD, Circle, Create, Dot, FadeIn, LaggedStart, Line, VGroup)

import _path  # noqa: F401
from hviz import data as D
from hviz.plot import Panel, mjd_label
from hviz.style import BLUE, GOLD, GREY, MUTED, TEXT, HScene, T, colorbar, seq_color

EVIDENCE = ["rw_aur_spherex-d1.json"]


def numbers():
    ev = D.target("rw_aur")
    epochs = {e["obs_id"]: e for e in ev["epochs"]}
    flux = {}
    for c in ev["comparisons"]:
        for side, lam in (("a", "lambda_a_um"), ("b", "lambda_b_um")):
            oid, f = c[side], c[f"flux_{side}"]
            # Epoch b is reprojected onto epoch a's pixel grid, so one exposure can carry
            # slightly different fluxes in different pairs. We keep every value and say so.
            rec = flux.setdefault(oid, {"values": [], "lambda_um": c[lam], "mjd": epochs[oid]["mjd"]})
            if not np.isclose(rec["lambda_um"], c[lam], rtol=1e-12):
                raise D.EvidenceError(f"two wavelengths for {oid}")
            rec["values"].append({"flux": f["flux"], "flux_err": f["flux_err"], "role": side})
    for rec in flux.values():
        v = [x["flux"] for x in rec["values"]]
        rec["flux"] = float(np.mean(v))
        rec["spread"] = (max(v) - min(v)) / rec["flux"]
    pairs = [(c["a"], c["b"], c["flux_a"]["flux"], c["flux_b"]["flux"]) for c in ev["comparisons"]]
    return {"epochs": ev["epochs"], "flux": flux, "pairs": pairs, "n_epochs": ev["n_epochs"],
            "n_with_flux": len(flux), "max_spread": max(r["spread"] for r in flux.values()),
            "caption": f'{ev["n_epochs"]} exposures · {len(flux)} with a per-epoch flux (members of the {len(pairs)} compared pairs)'}


class M10SpectralTime(HScene):
    SCENE_ID = "M10"
    TITLE = "RW Aur: wavelength and flux, exposure by exposure"
    LABELS = ("DATA-DRIVEN",)
    SOURCE = "SPHEREx DR1/QR3, NASA/IPAC IRSA · rw_aur_spherex-d1.json · HIPPARCHUS"

    def construct(self):
        n = numbers()
        t = [e["mjd"] for e in n["epochs"]]
        lam = [e["wavelength_um"] for e in n["epochs"]]
        tr = (min(t) - 15, max(t) + 15)
        ticks_t = [(v, mjd_label(v)) for v in np.linspace(tr[0] + 25, tr[1] - 25, 3)]
        lr = (min(lam) - 0.02, max(lam) + 0.02)
        left = Panel(tr, lr, 5.0, 4.1, x_label="time (UTC)", y_label="λ at the star (µm)", x_ticks=ticks_t,
                     y_ticks=[(v, f"{v:.2f}") for v in (0.8, 0.9, 1.0)], title="Where each exposure samples the spectrum",
                     size=13).move_to([-3.3, 0.35, 0])
        fl = n["flux"]
        fmax = max(v["flux"] for v in fl.values())
        fmin = min(v["flux"] for v in fl.values())
        col = lambda f: seq_color(0.25 + 0.75 * (f - fmin) / (fmax - fmin))  # noqa: E731
        dots = VGroup()
        for e in n["epochs"]:
            pnt = left.c2p(e["mjd"], e["wavelength_um"])
            if e["obs_id"] in fl:
                dots.add(Dot(pnt, radius=0.075, color=col(fl[e["obs_id"]]["flux"])))
            else:
                dots.add(Circle(radius=0.045, stroke_color=GREY, stroke_width=1.5).move_to(pnt))
        self.play(FadeIn(left), LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.01), run_time=1.2)

        rr = (min(v["lambda_um"] for v in fl.values()) - 0.01, max(v["lambda_um"] for v in fl.values()) + 0.01)
        right = Panel(tr, (0, fmax * 1.15), 5.0, 4.1, x_label="time (UTC)", y_label="flux (MJy/sr summed over pixels)",
                      x_ticks=ticks_t, y_ticks=[(v, f"{v:.0f}") for v in (50, 100, 150, 200) if v < fmax * 1.15],
                      title="Flux per exposure (not a light curve)", size=13).move_to([3.4, 0.35, 0])
        pts, bars = VGroup(), VGroup()
        for oid, v in fl.items():
            for m in v["values"]:
                p = right.c2p(v["mjd"], m["flux"])
                pts.add(Dot(p, radius=0.06, color=col(m["flux"])))
                bars.add(Line(right.c2p(v["mjd"], m["flux"] - m["flux_err"]), right.c2p(v["mjd"], m["flux"] + m["flux_err"]),
                              stroke_color=TEXT, stroke_width=2))
        links = VGroup(*[Line(right.c2p(fl[a]["mjd"], fa), right.c2p(fl[b]["mjd"], fb),
                              stroke_color=GOLD, stroke_width=1.5, stroke_opacity=0.8) for a, b, fa, fb in n["pairs"]])
        self.play(FadeIn(right), FadeIn(bars), LaggedStart(*[FadeIn(d) for d in pts], lag_ratio=0.05), run_time=1.2)
        self.play(Create(links), run_time=0.8)
        cb = colorbar(lambda x: seq_color(0.25 + 0.75 * x), f"{fmin:.0f}", f"{fmax:.0f}", "flux", height=1.6)
        cb.next_to(left.box, RIGHT, buff=0.12).align_to(left.box, UP)
        cap = VGroup(T(n["caption"], 15, TEXT),
                     T("Grey rings: no per-epoch flux in the evidence. Gold lines: the compared pairs, the only comparisons made.", 14, MUTED),
                     T(f"Each point is one exposure in one pair, never a coadd; reprojection moves a flux by up to {100*n['max_spread']:.1f}%. 1σ bars hide behind the dots.", 14, MUTED)
                     ).arrange(DOWN, aligned_edge=LEFT, buff=0.06).move_to([0, -2.75, 0])
        self.play(FadeIn(cb), FadeIn(cap), run_time=0.6)
        self.wait(1.5)
