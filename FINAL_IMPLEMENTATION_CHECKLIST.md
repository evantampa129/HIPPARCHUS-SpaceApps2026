# Final implementation checklist

Status as of 16 Nov 2026. Filled in from the commands we actually ran; this file is updated as the remaining items land.

| Feature | Status | Evidence | Tests | Limitations |
|---|---|---|---|---|
| Live IRSA search (DR1 + QR3) with checksums | IMPLEMENTED AND VERIFIED | `data/manifests/`, `submission/evidence/*.json` | backend test suite | Needs IRSA online; a down release is labelled PARTIAL |
| Per-epoch quality checks (flags, variance, wavelength at the star) | IMPLEMENTED AND VERIFIED | `rw_aur_spherex-d1.json` etc. | yes | Published numbers read WCS-WAVE with astropy's SIP shift; corrected `cwave` mode available (next row) |
| Wavelength calibration: SIP cause proven, selectable source `wcs` (legacy) / `wcs_nosip` / `cwave` (official CWAVE/CBAND) | IMPLEMENTED AND VERIFIED | `wavecal_check.json` (cause proven on 280 cutouts; legacy vs CWAVE up to 18 nm), `wavecal_robustness_{cwave,wcs_nosip}.json` | `test_spectral_cal.py` (8), `test_wavelength_source.py` (7) | Published numbers stay on legacy `wcs` for reproducibility; `cwave` changes only WISE 0855 (27→28 pairs, 1.93→2.05σ, 35/35 robust); no conclusion changes |
| ePSF zone layout (21×21; detector 3 11×41) | IMPLEMENTED AND VERIFIED | `wavecal_check.json` → `epsf_layout`, 204 cutouts | yes | — |
| Comparability rules and refusals | IMPLEMENTED AND VERIFIED | Barnard: 0/58 usable, refused | yes | — |
| Aperture photometry, difference and significance maps | IMPLEMENTED AND VERIFIED | RW Aur ×2.56, 175σ formal / ≈12σ with floor | yes | 6.15″ pixels: RW Aur A+B unresolved |
| Null test and SIMULATED injection-recovery | IMPLEMENTED AND VERIFIED | `validation.json` | yes | Three targets only |
| Stability fingerprint | IMPLEMENTED AND VERIFIED | `robustness.json` (24/24, 18/24, 34/34) | yes | Labels are rule-based, not probabilities |
| ePSF photometry (second measurement) + χ² diagnosis | IMPLEMENTED BUT EXPERIMENTAL | `epsf_check.json` (8/8 within 2%; `diagnostics`), `report/figures/epsf_diagnostics.png` | `test_epsf_options.py` (9, SIMULATED) + 3 | χ²_red 7.4 median → 3.2 with Gaia field stars and measured sky scale; residual core mismatch unexplained; not promoted to production |
| Evidence graph to DOIs | IMPLEMENTED AND VERIFIED | `graph_*.json` | yes | — |
| Catalogue match (SIMBAD, Gaia DR3) | IMPLEMENTED AND VERIFIED | `catalog_match.json` | — | CDS mirrors used during outage |
| Judge Mode page | IMPLEMENTED AND VERIFIED | `docs/index.html` (GitHub Pages) | built from evidence with asserts | Static, precomputed |
| Six-slide deck | IMPLEMENTED AND VERIFIED | `presentation/HIPPARCHUS_AETHENOVA_FINAL.pptx/.pdf` (6 pages) | assert in build script | — |
| Moving objects: blind linking validated on (216) Kleopatra vs JPL Horizons (observer = SPHEREx) | IMPLEMENTED (validation on one known asteroid) | `submission/evidence/motion_check.json`, `report/figures/motion_check.png` | `test_motion.py` (8, SIMULATED) | One object, one 3.3-day window, slow motion only; 3-visit tracks can be chance alignments; the second track is explained as two faint static Gaia/AllWISE stars plus one detector hit (`motion_followup.json`, `test_motion_vetting.py` 5 tests); further known-asteroid cases (Tamriko, Eros) found but not run because IRSA returned 502. HIPPARCHUS has not found Planet X |
| SPHEREx pipeline flags moving asteroids as OUTLIER (35/38 exposures) | FOUND AND DOCUMENTED | `motion_check.json` → `pipeline_flag_finding` | — | Motion check keeps OUTLIER pixels; static pipeline unchanged |
| Research report | IMPLEMENTED AND VERIFIED | `report/HIPPARCHUS_AETHENOVA_FINAL.pdf` (16 pages, XeLaTeX) | builds clean | — |
| 29 s film (Remotion) | IMPLEMENTED AND VERIFIED | `video/hipparchus_aethenova_29s.mp4` (29.4 s, 1920×1080, 30 fps, H.264 + AAC, −15.7 LUFS), `.en.srt`, `credits.txt`, `video/qc/` | ffprobe + QC frames | No voice-over (captions only); IRSA returned 502 during the screen recording, the app's cached listing is shown and labelled |
| First-person code comments pass | PARTIAL | new modules use "we"; older modules not fully rewritten | — | — |
| IRSA tools comparison (Spectrophotometry Tool, MOST, Source Discovery) | NOT IMPLEMENTED | — | — | Out of time |
| Spectral-response overlap diagnostic | NOT IMPLEMENTED | — | — | Pairing uses the |Δλ| ≤ half-channel rule instead |
| Observation compatibility graph | NOT IMPLEMENTED | — | — | Refusal reasons are listed per pair instead |
| `submission/` resource registry files (RESOURCE_INVENTORY.csv etc.) | NOT IMPLEMENTED | — | — | Covered by the "Data, credits and AI use" section of the README and `video/credits.txt` |
| Public interactive app (no login) | READY, NOT DEPLOYED | `deploy/` (free Hugging Face Docker Space), `backend/hipparchus/guard.py`; local image verified with a live RW Aur analysis | `test_guard.py` (10) | Needs the team to log in to Hugging Face once and run `deploy/deploy_space.sh --push`; Judge Mode on GitHub Pages is the public demo meanwhile |
| Machine-learning ranking | NOT IMPLEMENTED | — | — | No labelled data to train or test on fairly |

## Validated scientific results (reproduced from the evidence files)

- **RW Aur:** ×2.56 brighter in a year at 0.76 µm, 8/1540 valid pairs, 175σ formal (≈12σ with the 12.5% calibration
  floor); "×1.5 at ≥5σ" holds in 24/24 settings. Same in all three wavelength modes. RW Aur A+B are unresolved.
- **Barnard's Star:** comparison refused, 0/58 usable epochs (saturation/flags on the star).
- **WISE 0855:** no ≥5σ change, 27 pairs, max 1.93σ (legacy `wcs`); 28 pairs, max 2.05σ with official CWAVE/CBAND.
- **Wavelength:** astropy applies the celestial SIP terms to the spectral lookup table; proven on 280 cutouts; legacy
  differs from CWAVE by up to 18 nm. No published conclusion changes.
- **(216) Kleopatra:** blind linking over 7 SPHEREx visits; 0.15″/0.18″ rms against JPL Horizons computed from SPHEREx;
  rates within 0.8σ. The second track is two faint static stars plus one detector hit, not a mover.
- **HIPPARCHUS has not found Planet X.**

## Experimental

- ePSF photometry: 8/8 RW Aur ratios within 2% of aperture; χ²_red explained in part (field stars, sky structure),
  residual core mismatch unexplained. Not used for published numbers.
- `cwave` wavelength mode: validated, available, not the default for the published numbers.
- Degenerate-track check for moving objects: tested, not yet part of the published run.

## Remaining research opportunities

- Switch the default wavelength source to `cwave` in a new versioned release of the evidence.
- Joint PSF fit of RW Aur A and B and of field stars; understand the ePSF core mismatch.
- Run the prepared known-asteroid cases ((2052) Tamriko, (433) Eros, fast mover) once IRSA SIA is stable; wire the
  degenerate-track check into the linker; extend to many fields for unknown movers.
- Deploy the public interactive app (`deploy/`) on a free Hugging Face Space.
- Not implemented: IRSA tools comparison, spectral-response overlap diagnostic, observation compatibility graph.

## Public Release Verification

Checked on 16 Nov 2026.

| Item | Value |
|---|---|
| Private repo (`final-aethenova`) | `815115f` verified (this checklist update is the next commit); repository stays private |
| Public repo (`main`) | `9fd0cc0` verified and served by Pages (this checklist update is the next commit) |
| GitHub Pages | built from `9fd0cc0`; https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/ returns 200 with the updated Moving-Object Explorer |
| Backend tests | 106 passed (`cd backend && pytest -q`) |
| Frontend build | `npm run build` OK |
| Deck | 6 slides (PPTX + PDF) |
| Report | 16 pages |
| Video | 29.42 s, 1920×1080, 30 fps, H.264 + AAC; plays on the Judge Mode page with English captions |
| Public interactive app | ready in `deploy/`, verified locally with a live RW Aur analysis; not deployed (no host login on the build machine) |
| Links | every link on the page returns 200, except the IRSA archive-query links, which returned 502 because IRSA was down at check time |
| Secrets scan | no tokens, keys, `.env` or private e-mail in the public tree |
| Remaining issues | items marked NOT IMPLEMENTED / PARTIAL above; Space Apps portal submission is done by the team |
