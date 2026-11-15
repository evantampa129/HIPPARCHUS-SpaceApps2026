# HIPPARCHUS

Team **AITHENOVA**: NASA Space Apps Challenge 2026, *Planet X and SPHEREx* (Athens).

You give HIPPARCHUS a sky position (RA/Dec). It finds the real SPHEREx exposures of that field in NASA/IPAC IRSA, checks
each one (WCS, wavelength at the star, 18 quality flag planes, variance), and compares two epochs only when they were
seen at the same wavelength on the same detector. If a comparison isn't valid, it says so and gives the reason instead
of reporting a fake "detection".

We don't claim to have found Planet X or anything new. RW Aur comes out 2.5× brighter after a year. That is a
measurement of a star already known to vary, and it shows the method works.

## Layout

```
backend/      FastAPI + astropy: archive lookup, cutouts, quality checks, comparison, PNG rendering, tests
frontend/     React/TypeScript app (timeline, playback, blink, difference and significance maps)
submission/   evidence files with checksums, and the text for the submission page
report/       technical report (LaTeX + PDF), figures, bibliography
presentation/ 7-slide deck (PPTX + PDF), app screenshots, watermarked logos
video/        26 s demo video with English captions, and the scripts that made it
data/         archive listings (manifests); downloaded FITS go to data/cache (not in git)
```

## Running it

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest                                              # 19 tests, on real SPHEREx cutouts
cd ../frontend && npm install && npm run build      # builds frontend/dist
cd ../backend && uvicorn hipparchus.serve:app --port 8080   # app + API on http://localhost:8080
```

For development, run `uvicorn hipparchus.api:app --port 8077` and `npm run dev` (Vite proxies `/api` to 8077).
The first analysis of a target downloads its cutouts and takes 1–4 minutes. After that it reads from the cache.

## Reproducing the results

```bash
cd backend && python scripts/reproduce_evidence.py   # rewrites submission/evidence/*.json and the manifest
cd ../report && ./reproduce_report.sh               # figures + hipparchus_scientific_report.pdf
```

## Data, credits and use of AI

- Images: SPHEREx DR1 (doi:10.26131/IRSA678) and QR3 (doi:10.26131/IRSA662), NASA/IPAC Infrared Science Archive.
  Full citations are in `report/references.bib`.
- Software: Astropy, NumPy, SciPy, reproject, Matplotlib, FastAPI, React.
- An AI coding assistant helped write and review code, tests and documentation drafts. The team ran and checked
  everything. The logos are AI-generated and carry a visible "AI-generated" label. No data or results were generated
  by AI.
- This is independent work by team AITHENOVA. It is not a NASA publication, NASA has not endorsed it, and it uses no
  NASA branding.

MIT licence (see `LICENSE`).
