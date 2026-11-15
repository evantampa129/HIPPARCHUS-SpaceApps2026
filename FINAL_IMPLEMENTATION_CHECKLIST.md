# Final implementation checklist

Status as of 15 Nov 2026. Filled in from the commands we actually ran; this file is updated as the remaining items land.

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
| Machine-learning ranking | NOT IMPLEMENTED | — | — | No labelled data to train or test on fairly |
