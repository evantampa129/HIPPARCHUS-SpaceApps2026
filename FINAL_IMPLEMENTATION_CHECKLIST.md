# Final implementation checklist

Status as of 16 Nov 2026. Filled in from the commands we actually ran; this file is updated as the remaining items land.

| Feature | Status | Evidence | Tests | Limitations |
|---|---|---|---|---|
| Live IRSA search (DR1 + QR3) with checksums | IMPLEMENTED AND VERIFIED | `data/manifests/`, `submission/evidence/*.json` | backend test suite | Needs IRSA online; a down release is labelled PARTIAL |
| Per-epoch quality checks (flags, variance, wavelength at the star) | IMPLEMENTED AND VERIFIED | `rw_aur_spherex-d1.json` etc. | yes | Wavelength read from WCS-WAVE with a SIP shift (found by our audit, see next row) |
| CWAVE/CBAND calibration audit | IMPLEMENTED AND VERIFIED | `wavecal_check.json`: no published conclusion changes; WISE 0855 27 → 28 pairs, max 2.05σ | 8 tests (`test_spectral_cal.py`) | Audit only; pipeline still uses WCS-WAVE for reproducibility |
| ePSF zone layout (21×21; detector 3 11×41) | IMPLEMENTED AND VERIFIED | `wavecal_check.json` → `epsf_layout`, 204 cutouts | yes | — |
| Comparability rules and refusals | IMPLEMENTED AND VERIFIED | Barnard: 0/58 usable, refused | yes | — |
| Aperture photometry, difference and significance maps | IMPLEMENTED AND VERIFIED | RW Aur ×2.56, 175σ formal / ≈12σ with floor | yes | 6.15″ pixels: RW Aur A+B unresolved |
| Null test and SIMULATED injection-recovery | IMPLEMENTED AND VERIFIED | `validation.json` | yes | Three targets only |
| Stability fingerprint | IMPLEMENTED AND VERIFIED | `robustness.json` (24/24, 18/24, 34/34) | yes | Labels are rule-based, not probabilities |
| ePSF photometry (second measurement) | IMPLEMENTED BUT EXPERIMENTAL | `epsf_check.json` (8/8 within 2%) | 3 tests | χ²_red 4–18; not used for published numbers |
| Evidence graph to DOIs | IMPLEMENTED AND VERIFIED | `graph_*.json` | yes | — |
| Catalogue match (SIMBAD, Gaia DR3) | IMPLEMENTED AND VERIFIED | `catalog_match.json` | — | CDS mirrors used during outage |
| Judge Mode page | IMPLEMENTED AND VERIFIED | `docs/index.html` (GitHub Pages) | built from evidence with asserts | Static, precomputed |
| Six-slide deck | IMPLEMENTED AND VERIFIED | `presentation/HIPPARCHUS_AETHENOVA_FINAL.pptx/.pdf` (6 pages) | assert in build script | — |
| Moving objects: blind linking validated on (216) Kleopatra vs JPL Horizons (observer = SPHEREx) | IMPLEMENTED (validation on one known asteroid) | `submission/evidence/motion_check.json`, `report/figures/motion_check.png` | `test_motion.py` (8, SIMULATED) | One object, one 3.3-day window, slow motion only; 3-visit tracks can be chance alignments; a second unexplained track is reported, not claimed. HIPPARCHUS has not found Planet X |
| SPHEREx pipeline flags moving asteroids as OUTLIER (35/38 exposures) | FOUND AND DOCUMENTED | `motion_check.json` → `pipeline_flag_finding` | — | Motion check keeps OUTLIER pixels; static pipeline unchanged |
| Research report | IMPLEMENTED AND VERIFIED | `report/HIPPARCHUS_AETHENOVA_FINAL.pdf` (13 pages, XeLaTeX) | builds clean | — |
| 29 s film (Remotion) | IMPLEMENTED AND VERIFIED | `video/hipparchus_aethenova_29s.mp4` (29.4 s, 1920×1080, 30 fps, H.264 + AAC, −15.7 LUFS), `.en.srt`, `credits.txt`, `video/qc/` | ffprobe + QC frames | No voice-over (captions only); IRSA returned 502 during the screen recording, the app's cached listing is shown and labelled |
| First-person code comments pass | PARTIAL | new modules use "we"; older modules not fully rewritten | — | — |
| IRSA tools comparison (Spectrophotometry Tool, MOST, Source Discovery) | NOT IMPLEMENTED | — | — | Out of time |
| Spectral-response overlap diagnostic | NOT IMPLEMENTED | — | — | Pairing uses the |Δλ| ≤ half-channel rule instead |
| Observation compatibility graph | NOT IMPLEMENTED | — | — | Refusal reasons are listed per pair instead |
| `submission/` resource registry files (RESOURCE_INVENTORY.csv etc.) | NOT IMPLEMENTED | — | — | Covered by the "Data, credits and AI use" section of the README and `video/credits.txt` |
| Machine-learning ranking | NOT IMPLEMENTED | — | — | No labelled data to train or test on fairly |

## Public Release Verification

Checked on 16 Nov 2026, before the commit that adds this section.

| Item | Value |
|---|---|
| Private repo (`final-aethenova`) HEAD | `52f9698` (pushed; repository stays private) |
| Public repo (`main`) HEAD | `e6042d9` |
| GitHub Pages | built; latest build built e6042d9; https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/ returns 200 and shows the Moving-Object Explorer |
| Backend tests | 54 passed (`cd backend && pytest -q`) |
| Frontend build | `npm run build` OK |
| Deck | 6 slides (PPTX + PDF) |
| Report | 13 pages |
| Video | 29.42 s, 1920×1080, 30 fps, H.264 + AAC; plays on the Judge Mode page with English captions |
| Links | Pages: page, film, captions, figures, logos all 200; every relative link on the page 200. GitHub: report, deck (PDF/PPTX), film, evidence, AI disclosure, checklist all 200 |
| Secrets scan | no tokens, keys, `.env` or private e-mail in the public tree |
| Size | public tree ≈ 42 MB; largest file is the 7.8 MB film |
| Remaining issues | items marked NOT IMPLEMENTED / PARTIAL above; minor axis-label overlap in `motion_check.png`; Space Apps portal submission is done by the team, not by this repository |
