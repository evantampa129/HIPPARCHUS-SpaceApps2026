"""Build the 7-slide deck (Space Apps limit: 7 slides including the title).

    backend/.venv/bin/python presentation/build_deck.py
    soffice --headless --convert-to pdf presentation/hipparchus_7_slides.pptx --outdir presentation

Every number on the slides is copied from submission/evidence/*.json.
"""

import subprocess
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).parent
ROOT = HERE.parent
FIG = ROOT / "report" / "figures"
BG, TXT, MUTED, ACC, OK, WARN = "0B1020", "E6EBF5", "93A0BD", "7FD4FF", "4FD18B", "FFC857"

# Team members are added by the team; never invented here.
MEMBERS = "Evangelos Tampachaniotis"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def png(fig):
    # The report keeps vector PDFs; slides need raster images.
    out = HERE / "screens" / f"fig_{fig}.png"
    if not out.exists():
        subprocess.run(["pdftoppm", "-r", "220", "-png", "-singlefile", str(FIG / f"{fig}.pdf"), str(out.with_suffix(""))], check=True)
    return out


def slide(title=None):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid(); s.background.fill.fore_color.rgb = RGBColor.from_string(BG)
    if title:
        text(s, title, 0.6, 0.35, 12.1, 0.9, 32, bold=True)
    # Footer on every slide: data credit and the independence statement.
    text(s, "Data: NASA SPHEREx via NASA/IPAC IRSA · Team AITHENOVA · NASA Space Apps Challenge 2026 · independent project, not endorsed by NASA",
         0.6, 7.0, 12.1, 0.35, 10, color=MUTED)
    return s


def text(s, body, x, y, w, h, size=18, bold=False, color=TXT):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame; tf.word_wrap = True
    lines = body if isinstance(body, list) else [body]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        txt, c, sz, b = (line + (None,) * 3)[:4] if isinstance(line, tuple) else (line, None, None, None)
        r = p.add_run(); r.text = txt
        r.font.size = Pt(sz or size); r.font.bold = bold if b is None else b
        r.font.color.rgb = RGBColor.from_string(c or color); r.font.name = "DejaVu Sans"
        p.space_after = Pt(6)
    return tb


def pic(s, path, x, y, w=None, h=None):
    return s.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w) if w else None, Inches(h) if h else None)


# 1. Title
s = slide()
pic(s, HERE / "assets" / "hipparchus-logo_ai.png", 3.67, 0.5, w=6)
text(s, "Has this star changed?", 0.6, 3.75, 12.1, 0.8, 36, bold=True)
text(s, ["Validated multi-epoch comparison of real NASA SPHEREx images",
         ("Challenge: Planet X and SPHEREx · Team AITHENOVA · Athens", ACC),
         (MEMBERS, TXT, 18)], 0.6, 4.6, 12.1, 2, 20, color=MUTED)
text(s, "Logos: AI-generated (watermarked)", 9.8, 6.6, 3, 0.35, 10, color=MUTED)

# 2. Problem
s = slide("Why not just subtract two SPHEREx images?")
text(s, [("SPHEREx images the whole sky again and again in 102 colours (0.75–5 µm). Great for finding what changes. But:", TXT),
         ("•  Linear variable filters: the same star is seen at a different wavelength in every visit. A brightness 'change' can just be its spectrum.", TXT),
         ("•  Bright stars saturate. Barnard's Star is flagged OVERFLOW in 56 of 58 epochs.", TXT),
         ("•  Zodiacal light changes with the season and adds false background changes.", TXT),
         ("Result: naive differencing invents variability. We need a tool that knows when a comparison is valid, and says no when it is not.", ACC, 20, True)],
     0.6, 1.4, 12.1, 5.4, 20)

# 3. How it works
s = slide("How HIPPARCHUS works, on real NASA data")
text(s, [("1. Search: IRSA SIA v2, SPHEREx DR1 (doi:10.26131/IRSA678) + QR3 (doi:10.26131/IRSA662), live, with SHA-256 of every archive answer", TXT),
         ("2. Cutouts: 0.05° server-side FITS cutouts, cached and checksum-verified", TXT),
         ("3. Check each epoch: zodiacal model removed, wavelength read AT the star, 18 pipeline flag planes, variance, edges", TXT),
         ("4. Pair only if same detector and Δλ ≤ ½ channel; otherwise refuse with a reason", TXT),
         ("5. Compare: reprojection, aperture photometry with errors, significance map, centroid shift, control star", TXT),
         ("6. Evidence file: every identifier, checksum, setting and output, reproducible with one script", TXT),
         ("Stack: Python · FastAPI · Astropy · reproject · React/TypeScript. 35 tests on real SPHEREx cutouts. MIT licence.", MUTED, 16)],
     0.6, 1.4, 12.1, 5.5, 19)

# 4. Demo
s = slide("The app: search, check, blink, compare")
pic(s, HERE / "screens" / "04_comparison.png", 0.6, 1.3, w=7.6)
pic(s, HERE / "screens" / "02_summary.png", 8.4, 1.3, w=4.4)
text(s, ["Enter coordinates or pick a star → live archive search → every epoch on a real time axis → playback of usable epochs → blink, difference and ±5σ significance map → refusal reasons in plain words → evidence download.",
         ("Screenshots of the running app, real data.", MUTED, 14)], 0.6, 5.7, 12.1, 1.2, 16)

# 5. Result A
s = slide("Result A: RW Aur, 2.5x brighter in a year")
pic(s, png("rwaur_pair"), 0.6, 1.3, w=7.4)
pic(s, png("rwaur_ratios"), 8.2, 1.3, w=4.6)
text(s, [("8 valid pairs out of 1540 (1480 fail the wavelength test, 1387 involve saturated epochs).", TXT),
         ("Strongest: 2025-09 → 2026-09 at 0.763/0.770 µm: flux ×2.56, 175σ formal. All 8 pairs brighter later; chain ×1.67 then ×1.42 agrees.", OK),
         ("Control star in the same images: ×0.86–1.07, |σ| ≤ 2.2, so calibration agrees. Centroid shift < 0.8″.", TXT),
         ("RW Aur is a known variable young binary (both stars in our aperture): a measurement, not a discovery.", MUTED, 15)],
     0.6, 4.35, 12.1, 2.6, 17)

# 6. Results B and C
s = slide("Result B: knowing when to say no")
pic(s, HERE / "screens" / "05_refusal.png", 0.6, 1.3, w=7.2)
pic(s, png("pair_outcomes"), 8.0, 1.3, w=4.8)
text(s, [("Barnard's Star: 58 epochs, 0 usable: saturation flags on the star in every one. No comparison is made; the reasons are shown.", WARN),
         ("WISE 0855 (coldest brown dwarf): 27 valid pairs, no change above 1.9σ. The scatter of significances (0.83) shows the error bars are honest. Too faint to constrain, and we say so.", TXT)],
     8.0, 3.7, 4.9, 3.2, 15)

# 7. Impact
s = slide("Impact and next steps")
text(s, [("Impact: anyone can ask 'has this star changed?' of SPHEREx data and get an answer that respects the instrument, or a clear refusal.", TXT),
         ("Creativity: a variability tool whose main feature is refusing invalid comparisons; LVF-aware wavelength matching; built-in control star.", TXT),
         ("Validity: real DR1/QR3 data, checksums, 35 tests, control stars, blank-sky null test (spread 0.91, ideal 1), SIMULATED injection-recovery (44% at S/N 5, 99% at 7), evidence graph to DOIs, SIMBAD + Gaia DR3 match, stability checks (main claims robust in 24/24 and 34/34 checks), 8-page report.", TXT),
         ("AI use: logos (watermarked) and video assembly, reference cross-checks, coding assistant. All code run and tested by me; all results from real SPHEREx images.", MUTED, 15),
         ("Next: proper-motion search for Planet X-like movers across fields, PSF photometry to separate blended stars (RW Aur is a 1.6″ binary), all-sky cube.", ACC),
         ],
     0.6, 1.4, 12.1, 5.5, 18)

out = HERE / "hipparchus_7_slides.pptx"
# python-pptx keeps the author of its own template file unless we set it.
cp = prs.core_properties
cp.author = cp.last_modified_by = MEMBERS
cp.title = "HIPPARCHUS: has this star changed?"
prs.save(out)
assert len(prs.slides) <= 7
print(out, len(prs.slides), "slides")
