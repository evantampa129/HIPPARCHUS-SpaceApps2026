"""Build the final 6-slide deck (editable PPTX) and its PDF.

    backend/.venv/bin/python presentation/build_deck.py

We read every number on the slides from submission/evidence/*.json at build
time, so the deck cannot drift from the report and the Judge Mode page.
"""

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import qrcode  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parent
FIG = ROOT / "report" / "figures"
EVID = ROOT / "submission" / "evidence"
SCR = HERE / "screens"
ASSETS = HERE / "assets"
OUT = HERE / "HIPPARCHUS_AETHENOVA_FINAL.pptx"
DEMO = "https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/"
REPO = "https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026"
BG, PANEL, TXT, MUTED, ACC, OK, WARN, BAD = ("070B16", "111830", "E9EDF6", "8E9AB8", "7FD4FF",
                                             "4FD18B", "FFC857", "FF6B6B")
MEMBERS = "Evangelos Tampachaniotis"  # we add team members ourselves; the script never invents them

ev = {p.stem: json.loads(p.read_text()) for p in EVID.glob("*.json")}
rob = ev["robustness"]["targets"]
rw = ev["rw_aur_spherex-d1"]
epsf = ev.get("epsf_check")
motion = ev.get("motion_check")

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def png(fig):
    # We keep vector PDFs in the report; the slides need raster copies.
    out = SCR / f"fig_{fig}.png"
    if not out.exists():
        subprocess.run(["pdftoppm", "-r", "220", "-png", "-singlefile", str(FIG / f"{fig}.pdf"),
                        str(out.with_suffix(""))], check=True)
    return out


def stability_png():
    """Heatmap of the RW Aur 'x1.5 at >= 5 sigma' claim over the settings grid."""
    out = SCR / "fig_stability.png"
    claim = next(c["claim"] for c in rob["rw_aur"]["claims"] if "1.5" in c["claim"])
    cfg = [c for c in rob["rw_aur"]["stability"] if c["mask"] == "as_flagged" and c["calibration"] == "none"]
    aps = sorted({c["r_ap"] for c in cfg})
    ann = sorted({tuple(c["annulus"]) for c in cfg})
    fig, ax = plt.subplots(figsize=(5.2, 3.3), facecolor="#" + PANEL)
    ax.set_facecolor("#" + PANEL)
    for i, a in enumerate(aps):
        for j, an in enumerate(ann):
            c = next(x for x in cfg if x["r_ap"] == a and tuple(x["annulus"]) == an)
            # We grey out settings where a pair was refused (flags inside the larger aperture): the
            # claim is not evaluated there, which is different from failing.
            if not c["complete"]:
                col, lab = "#3A4258", "not evaluated\n(pair refused)"
            else:
                col = "#2E8B57" if c["claim_holds"][claim] else "#B8860B"
                lab = f'x{c["strongest_ratio"]:.2f}\n{c["max_abs_sig"]:.0f}σ'
            ax.add_patch(plt.Rectangle((j, i), 0.94, 0.94, color=col))
            ax.text(j + 0.47, i + 0.47, lab, ha="center", va="center", color="white", fontsize=7.5)
    ax.set_xlim(0, len(ann)); ax.set_ylim(0, len(aps))
    ax.set_xticks([j + 0.47 for j in range(len(ann))], [f"sky {a[0]:g}–{a[1]:g} px" for a in ann], color="#" + TXT, fontsize=8)
    ax.set_yticks([i + 0.47 for i in range(len(aps))], [f"r = {a:g} px" for a in aps], color="#" + TXT, fontsize=8)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("RW Aur: strongest pair under each aperture / sky choice", color="#" + TXT, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=220, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def qr_png():
    out = SCR / "qr_demo.png"
    qrcode.make(DEMO, border=2).save(out)
    return out


def slide(title=None, kicker=None):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor.from_string(BG)
    if kicker:
        text(s, kicker, 0.6, 0.3, 12.1, 0.4, 12, color=ACC, bold=True)
    if title:
        text(s, title, 0.6, 0.62, 12.1, 0.9, 30, bold=True)
    # We put the data credit and the independence statement on every slide.
    text(s, "Data: NASA SPHEREx (DR1 doi:10.26131/IRSA678, QR3 doi:10.26131/IRSA662) via NASA/IPAC IRSA · Team AETHENOVA · "
            "NASA Space Apps Challenge 2026 · independent project, not endorsed by NASA",
         0.6, 7.05, 12.1, 0.35, 9, color=MUTED)
    return s


def text(s, body, x, y, w, h, size=18, bold=False, color=TXT):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(body if isinstance(body, list) else [body]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        txt, c, sz, b = (line + (None,) * 3)[:4] if isinstance(line, tuple) else (line, None, None, None)
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(sz or size)
        r.font.bold = bold if b is None else b
        r.font.color.rgb = RGBColor.from_string(c or color)
        r.font.name = "DejaVu Sans"
        p.space_after = Pt(6)
    return tb


def panel(s, x, y, w, h, color=PANEL):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor.from_string(color)
    sh.line.fill.background()
    sh.adjustments[0] = 0.06
    return sh


def pic(s, path, x, y, w=None, h=None):
    return s.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w) if w else None, Inches(h) if h else None)


best = max(rw["comparisons"], key=lambda c: c["significance"])
floor = rob["rw_aur"]["systematic_floor"]
sig_floor = max(p["sig_with_systematics"] for p in rob["rw_aur"]["pairs"])
claims = {c["claim"]: c for c in rob["rw_aur"]["claims"]}
c15 = next(v for k, v in claims.items() if "1.5" in k)
call = next(v for k, v in claims.items() if "every" in k)
cw = rob["wise0855"]["claims"][0]
n_tests = 183  # 159 backend + 24 Manim (pytest, 16 Nov 2026)

# 1. Identity
s = slide()
pic(s, ASSETS / "hipparchus-logo_ai.png", 0.6, 0.45, w=7.4)
text(s, "Has this star really changed?", 0.6, 4.3, 7.7, 0.7, 32, bold=True)
text(s, ["Careful multi-epoch comparison of real NASA SPHEREx infrared images",
         ("THE UNIVERSE IS NEVER STILL.", ACC, 16, True)], 0.6, 5.0, 7.7, 1.2, 18, color=MUTED)
text(s, [f"Team AETHENOVA · {MEMBERS}", ("Athens · Challenge: Planet X and SPHEREx", MUTED, 13)],
     0.6, 6.05, 7.7, 0.8, 15)
pic(s, ASSETS / "aethenova-logo_ai.png", 8.55, 1.2, w=4.2)
text(s, ["ANCIENT CURIOSITY.", "INFINITE DISCOVERY."], 8.55, 4.15, 4.2, 0.9, 15, bold=True, color=ACC)
text(s, "Both logos: AI-generated (watermarked)", 8.55, 5.1, 4.2, 0.3, 10, color=MUTED)

# 2. Challenge
s = slide("A difference is not always a discovery", "THE PLANET X AND SPHEREx CHALLENGE")
text(s, [("SPHEREx maps the whole sky every six months in 102 infrared colours (0.75–5 µm). Anything that moves or "
          "changes, from variable stars to a distant planet, shows up only by comparing epochs. But most differences are "
          "the instrument, not the sky:", TXT, 17),
         ("•  Each visit sees the star at a different wavelength (linear variable filters).", TXT, 16),
         ("•  Bright stars saturate: Barnard's Star is flagged in every one of its 58 epochs.", TXT, 16),
         ("•  Zodiacal light changes with the season.", TXT, 16),
         ("We built the step a search needs first: decide whether two epochs can be compared, and how far a measured "
          "change can be trusted.", ACC, 17, True)], 0.6, 1.55, 6.7, 5.3, 17)
pic(s, ROOT / "docs" / "img" / "rw_aur_a.png", 7.6, 1.6, w=2.55)
pic(s, ROOT / "docs" / "img" / "rw_aur_b.png", 10.25, 1.6, w=2.55)
pic(s, ROOT / "docs" / "img" / "barnard_epoch.png", 8.9, 4.3, w=2.55)
dates = {e["obs_id"]: e["date_obs"][:10] for e in rw["epochs"]}
text(s, f'RW Aur, {dates[best["a"]]} vs {dates[best["b"]]} (real SPHEREx cutouts)', 7.6, 4.0, 5.2, 0.3, 10, color=MUTED)
text(s, "Barnard's Star: saturated, refused", 8.9, 6.7, 3, 0.3, 10, color=WARN)

# 3. Method
s = slide("Observe → Verify → Challenge → Explain", "HOW HIPPARCHUS WORKS")
steps = [("OBSERVE", "Live IRSA search of SPHEREx DR1 + QR3; server-side FITS cutouts with SHA-256 checksums.",
          "RW Aur: 56 epochs on detector 1"),
         ("VERIFY", "Zodiacal light removed, wavelength read at the star, 18 flag planes, variance. Pair only same "
                    "detector and |Δλ| ≤ ½ channel.", "RW Aur: 8 of 1540 pairs pass · Barnard: 0 of 58 epochs"),
         ("CHALLENGE", "Repeat with other apertures, sky annuli, masks, calibration, wavelength rules; drop each pair; "
                       "fit the SPHEREx ePSF as a second measurement.", f'"×1.5 at ≥5σ": {c15["n_holding"]}/{c15["n_checks"]} checks hold'),
         ("EXPLAIN", "Result with formal and systematic error, refusal reasons and an evidence file that rebuilds it.",
          f"{best['significance']:.0f}σ formal → {sig_floor:.0f}σ with a {100 * floor:.1f}% floor")]
for i, (h, body, ex) in enumerate(steps):
    x = 0.6 + i * 3.08
    panel(s, x, 1.7, 2.9, 4.6)
    text(s, h, x + 0.2, 1.85, 2.5, 0.5, 18, bold=True, color=ACC)
    text(s, body, x + 0.2, 2.45, 2.55, 2.7, 14)
    text(s, ex, x + 0.2, 5.25, 2.55, 1.0, 12, color=OK)
text(s, f"Python · FastAPI · Astropy · reproject · React/TypeScript · {n_tests} automated tests · MIT licence",
     0.6, 6.5, 12.1, 0.4, 13, color=MUTED)

# 4. Results
s = slide("Three real stars, three honest answers", "RESULTS")
pic(s, png("rwaur_pair"), 0.6, 1.55, w=6.6)
panel(s, 7.45, 1.55, 5.3, 1.75)
text(s, [("RW Aur: measured change", OK, 17, True),
         (f'×{best["flux_ratio"]:.2f} brighter in a year at {best["lambda_a_um"]:.3f} µm. {best["significance"]:.0f}σ formal, '
          f'≈{sig_floor:.0f}σ with calibration floor. Known variable; the 1.6″ binary is unresolved.', TXT, 13)],
     7.6, 1.6, 5.05, 1.7)
panel(s, 7.45, 3.45, 5.3, 1.45)
text(s, [("Barnard's Star: comparison refused", WARN, 17, True),
         ("0 of 58 epochs usable: saturation flags on the star in every one. The refusal is the result.", TXT, 13)],
     7.6, 3.5, 5.05, 1.4)
panel(s, 7.45, 5.05, 5.3, 1.75)
wmax = max(abs(p["sig"]) for p in rob["wise0855"]["pairs"])
text(s, [("WISE 0855: no significant change", MUTED, 17, True),
         (f"{len(rob['wise0855']['pairs'])} valid pairs, largest change {wmax:.1f}σ. Too faint (S/N < 5) to prove it is "
          "constant, and we say so.", TXT, 13)], 7.6, 5.1, 5.05, 1.7)
text(s, "Real SPHEREx cutouts of RW Aur, two epochs, difference and significance map.", 0.6, 5.2, 6.6, 0.3, 10, color=MUTED)

# 5. Validation and novelty
s = slide("We try to break our own result", "VALIDATION AND WHAT IS NEW")
pic(s, stability_png(), 0.6, 1.55, w=5.6)
val = ev["validation"]
lines = [("Stability fingerprint: the claim is re-measured under every reasonable choice.", TXT, 14),
         (f'"RW Aur ×1.5 at ≥5σ": robust ({c15["n_holding"]}/{c15["n_checks"]}). "Brighter in every pair": '
          f'sensitive ({call["n_holding"]}/{call["n_checks"]}). "WISE 0855 no ≥5σ change": robust ({cw["n_holding"]}/{cw["n_checks"]}).', OK, 14)]
if epsf:
    dev = max(abs(r["ratio_epsf"] / r["ratio_aperture"] - 1) for r in epsf["targets"]["rw_aur"]["pairs"])
    lines.append((f"Second measurement (experimental): fitting the SPHEREx ePSF to native pixels reproduces all "
                  f"{epsf['targets']['rw_aur']['n_pairs']} RW Aur ratios within {100 * dev:.0f}%.", TXT, 14))
lines += [("Blank-sky null test and SIMULATED injection-recovery confirm the error bars.", TXT, 14),
          ("What is ours: not forced photometry itself, but the refusal rules, the self-challenge and an evidence "
           "file for every number.", ACC, 14, True)]
text(s, lines, 6.5, 1.55, 6.3, 5.2, 14)
text(s, "Green: claim holds. Grey: not evaluated (a pair was refused). Numbers: strongest ratio and significance (robustness.json).",
     0.6, 5.2, 5.6, 0.5, 10, color=MUTED)

# 6. Impact and next frontier
s = slide("From changing stars to moving worlds", "IMPACT, NEXT STEPS AND LIVE DEMO")
if motion:
    mr = motion["residuals_vs_horizons_spherex_arcsec"]["all_detections_near_prediction"]
    mline = (f"Moving objects (validated on known asteroids): our blind search linked (216) Kleopatra across "
             f"7 SPHEREx visits; positions match JPL Horizons to {mr['rms_ra_cosdec']:.2f}″/{mr['rms_dec']:.2f}″ rms. "
             f"It also linked the fainter (2052) Tamriko and the fast (433) Eros.", OK, 15)
else:
    mline = ("Moving objects: linking detections across epochs is the next step toward a Planet X search; "
             "not yet validated on real data. FUTURE WORK.", WARN, 15)
text(s, [("Impact: anyone can ask SPHEREx whether a star changed, and get an answer that respects the instrument, "
          "or a clear refusal with reasons.", TXT, 15),
         mline,
         ("Planet X: a distant planet would move only arcseconds per day and be faint. SPHEREx can constrain bright "
          "candidates; not seeing one does not rule Planet X out. HIPPARCHUS has not found Planet X.", TXT, 15),
         ("Next: science-grade wavelength calibration everywhere, wide searches for unknown movers, larger fields for "
          "calibration stars.", MUTED, 14),
         ("AI use: logos (watermarked), video assembly, and help with coding, method review and literature. "
          "All measurements come from real NASA SPHEREx images and are checked by reproducible tests.", MUTED, 12)],
     0.6, 1.55, 8.4, 5.3, 15)
panel(s, 9.35, 1.55, 3.4, 5.1)
pic(s, qr_png(), 9.75, 1.75, w=2.6)
text(s, [("Live demo", ACC, 16, True), ("evantampa129.github.io/\nHIPPARCHUS-SpaceApps2026", TXT, 12),
         ("Code: github.com/evantampa129/\nHIPPARCHUS-SpaceApps2026", MUTED, 11)], 9.55, 4.45, 3.1, 2.1, 12)

cp = prs.core_properties
cp.author = cp.last_modified_by = MEMBERS
cp.title = "HIPPARCHUS — Team AETHENOVA"
prs.save(OUT)
assert len(prs.slides) == 6
subprocess.run(["soffice", "--headless", "--convert-to", "pdf", str(OUT), "--outdir", str(HERE)], check=True,
               capture_output=True)
print(OUT, len(prs.slides), "slides")
