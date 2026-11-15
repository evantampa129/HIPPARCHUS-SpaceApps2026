# HIPPARCHUS

Team **AITHENOVA**: NASA Space Apps Challenge 2026, *Planet X and SPHEREx* (Athens).

**Observe → verify → challenge → explain.** You give HIPPARCHUS a sky position (RA/Dec). It finds the real SPHEREx exposures of that field in NASA/IPAC IRSA, checks
each one (WCS, wavelength at the star, 18 quality flag planes, variance), and compares two epochs only when they were
seen at the same wavelength on the same detector. If a comparison isn't valid, it says so and gives the reason instead
of reporting a fake "detection".

We don't claim to have found Planet X or anything new. RW Aur comes out 2.5× brighter after a year. That is a
measurement of a star already known to vary (and, at 6.15″ pixels, of both stars of the binary together), and it
shows the method works. Its 175σ is a formal significance; with the 12.5% calibration scatter of the field stars it
is about 12σ.

A static **Judge Mode** page with the three cases (images, dates, uncertainties, stability heatmap, limitations and
an evidence capsule per target) is in `docs/` and is rebuilt by `backend/scripts/make_judge_site.py`.

## Layout

```
backend/      FastAPI + astropy: archive lookup, cutouts, quality checks, comparison, PNG rendering, tests
frontend/     React/TypeScript app (timeline, playback, blink, difference and significance maps)
submission/   evidence files with checksums
report/       technical report (LaTeX + PDF), figures, bibliography
presentation/ 7-slide deck (PPTX + PDF), app screenshots, watermarked logos
video/        26 s demo video with English captions, and the scripts that made it
data/         archive listings (manifests); downloaded FITS go to data/cache (not in git)
```

## Running it

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest                                              # 35 tests, on real SPHEREx cutouts
cd ../frontend && npm install && npm run build      # builds frontend/dist
cd ../backend && uvicorn hipparchus.serve:app --port 8080   # app + API on http://localhost:8080
```

For development, run `uvicorn hipparchus.api:app --port 8077` and `npm run dev` (Vite proxies `/api` to 8077).
The first analysis of a target downloads its cutouts and takes 1–4 minutes. After that it reads from the cache.

## How we know the method works

- **Null test:** the same photometry is run at blank positions in every valid image pair. The significances spread
  0.91 (1 means exact error bars, n = 93) and none goes beyond 3σ, so the error bars are right or a little too large.
- **Injection-recovery (simulated):** fake stars of known brightness are added to the later image. 44% are found
  at S/N 5, 87% at 6 and 99% at 7, as a 5σ threshold should give. These fake stars are only used in
  `validation.json` and are always labelled SIMULATED.
- **Evidence graph:** `submission/evidence/graph_*.json` links every result to its cutout checksum, the archive
  answer and the dataset DOI. A test fails if any link is broken.
- **Control stars** in the same images stay within 0.86–1.07 while RW Aur changes by ×2.5.
- **Catalogue match:** SIMBAD and Gaia DR3 confirm that all three preset positions are on the right object (within
  0.2–0.9 pixels, after proper motion). It also shows that the RW Aur aperture holds both stars of the binary, and the
  WISE 0855 aperture a G = 16.3 field star 6.8″ away. The main CDS servers were offline after a cybersecurity incident
  (notice on cds.unistra.fr, 9 Nov 2026), so the script uses the mirrors CDS recommends and IRSA's copy of Gaia DR3.

- **Robustness:** each conclusion is rechecked with other aperture radii (1.5–3 px), sky annuli, grown masks, a
  calibration on all clean field stars, each pair left out in turn, a 12.5% calibration floor and stricter or looser
  wavelength rules. "RW Aur brightened ×1.5 or more at ≥5σ" and "WISE 0855 shows no ≥5σ change" hold in every check
  (robust); "RW Aur is brighter in every pair" fails with a 1.5 px aperture (sensitive). These labels follow a fixed
  rule and are not probabilities. The app shows them as a heatmap, read from `submission/evidence/robustness.json`.
- **Audit fixes:** the photometry now refuses a pair if a flagged pixel is in the aperture or the sky annulus is
  empty (before, the sky silently became zero), and the per-pixel significance map uses the right variance after
  bilinear reprojection. Neither changed a published number.

Not done: any machine-learning ranking. With three targets and no labelled examples there is nothing to train or
test one on fairly.

## Reproducing the results

```bash
cd backend && python scripts/reproduce_evidence.py   # rewrites submission/evidence/*.json and the manifest
python scripts/reproduce_validation.py              # null test, injection-recovery, spectra, evidence graphs, timings
python scripts/reproduce_catalogs.py                # SIMBAD + Gaia DR3 match of the targets (needs network)
python scripts/reproduce_robustness.py              # audit and stability checks on the cached cutouts (~30 s)
cd ../report && ./reproduce_report.sh               # figures + hipparchus_scientific_report.pdf
```

## Data and credits

- Images: SPHEREx DR1 (doi:10.26131/IRSA678) and QR3 (doi:10.26131/IRSA662), NASA/IPAC Infrared Science Archive.
  Full citations are in `report/references.bib`.
- Software: Astropy, NumPy, SciPy, reproject, Matplotlib, FastAPI, React.
- AI tools were used mainly for the graphics (the logos, watermarked "AI-generated", and putting together the
  demo video), to cross-check the NASA/IRSA dataset references, and as a coding assistant. All code was run and
  tested by me; every measurement comes from real SPHEREx images.
- This is independent work by team AITHENOVA. It is not a NASA publication, NASA has not endorsed it, and it uses no
  NASA branding.

MIT licence (see `LICENSE`).
