# HIPPARCHUS scene library (Manim)

Ten short animated scenes (3–8 s each) for the film, the slides and the Judge Mode page. Every number on screen is
read from `submission/evidence/*.json` at render time, and every frame carries a label (DATA-DRIVEN, SIMULATED,
CONCEPTUAL, HISTORICAL ILLUSTRATION, EXPERIMENTAL) and a source line.

| Scene | What it shows | Label |
|---|---|---|
| M01 | schematic ancient sky → RA/Dec grid, our three targets | CONCEPTUAL (+ HISTORICAL ILLUSTRATION tag on the chart) |
| M02 | channel response at two wavelengths, overlap, compatible vs refused pair | DATA-DRIVEN, curves tagged MODEL (top-hat / Gaussian surrogate) |
| M03 | r = 2 px aperture, 4–7 px sky annulus on real RW Aur pixels | DATA-DRIVEN |
| M04 | ePSF data / model / residual, reduced χ² as it is | DATA-DRIVEN + EXPERIMENTAL |
| M05 | Stability Fingerprint 24/24, 18/24, 34/34 | DATA-DRIVEN |
| M06 | (216) Kleopatra: observed vs JPL Horizons (from SPHEREx) vs fitted, residuals ×60 | DATA-DRIVEN |
| M07 | shift-and-stack over a velocity grid | CONCEPTUAL + SIMULATED |
| M08 | Observe → Verify → Challenge → Explain: Barnard refused, RW Aur supported | DATA-DRIVEN |
| M09 | observation compatibility graph for the three targets | DATA-DRIVEN |
| M10 | RW Aur wavelength and flux per exposure (never a coadd) | DATA-DRIVEN |

## Setup

Needs Cairo, Pango and FFmpeg from the system (no LaTeX: all text is set with Pango in Inter).

```bash
cd visualizations/manim
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

M03 and M04 draw real pixels. We extract them once from the cached cutout with the backend's own loader and ePSF
fit; the script stops if the cutout's SHA-256 or the fitted χ² differ from the evidence:

```bash
backend/.venv/bin/python visualizations/manim/tools/extract_pixels.py   # writes data/rw_aur_pixels.json
```

## Render

```bash
./render.sh          # all scenes: renders/*.mp4 + *.png, docs/media/manim/*.mp4 + *_poster.png, MANIFEST.json
./render.sh m06      # one scene
.venv/bin/python -m pytest -q tests   # numbers on screen == evidence, labels and source line present
```

`renders/` holds the 1080p30 H.264 masters and a still per scene; `docs/media/manim/` holds 720p web copies
(≤ 2 MB) with poster frames. `MANIFEST.json` lists each scene's labels, the evidence files with their SHA-256, the
outputs and the duration.

Layout: `hviz/style.py` (palette, fonts, frame labels), `hviz/data.py` (evidence loader and unit checks),
`hviz/plot.py` (panels without LaTeX), `scenes/` (one file per scene, each with a `numbers()` function the tests
check), `tools/` (pixel extract, manifest).
