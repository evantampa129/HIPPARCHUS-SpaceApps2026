# Final implementation checklist

Status as of 15 Nov 2026. Filled in from the commands we actually ran; this file is updated as the remaining items land.

| Feature | Status | Evidence | Tests | Limitations |
|---|---|---|---|---|
| Live IRSA search (DR1 + QR3) with checksums | IMPLEMENTED AND VERIFIED | `data/manifests/`, `submission/evidence/*.json` | backend test suite | Needs IRSA online; a down release is labelled PARTIAL |
| Per-epoch quality checks (flags, variance, wavelength at the star) | IMPLEMENTED AND VERIFIED | `rw_aur_spherex-d1.json` etc. | yes | Wavelength from WCS-WAVE (approximate); CWAVE/CBAND audit in progress |
| Comparability rules and refusals | IMPLEMENTED AND VERIFIED | Barnard: 0/58 usable, refused | yes | — |
| Aperture photometry, difference and significance maps | IMPLEMENTED AND VERIFIED | RW Aur ×2.56, 175σ formal / ≈12σ with floor | yes | 6.15″ pixels: RW Aur A+B unresolved |
| Null test and SIMULATED injection-recovery | IMPLEMENTED AND VERIFIED | `validation.json` | yes | Three targets only |
| Stability fingerprint | IMPLEMENTED AND VERIFIED | `robustness.json` (24/24, 18/24, 34/34) | yes | Labels are rule-based, not probabilities |
| ePSF photometry (second measurement) | IMPLEMENTED BUT EXPERIMENTAL | `epsf_check.json` (8/8 within 2%) | 3 tests | χ²_red 4–18; not used for published numbers |
| Evidence graph to DOIs | IMPLEMENTED AND VERIFIED | `graph_*.json` | yes | — |
| Catalogue match (SIMBAD, Gaia DR3) | IMPLEMENTED AND VERIFIED | `catalog_match.json` | — | CDS mirrors used during outage |
| Judge Mode page | IMPLEMENTED AND VERIFIED | `docs/index.html` (GitHub Pages) | built from evidence with asserts | Static, precomputed |
| Six-slide deck | IMPLEMENTED AND VERIFIED | `presentation/HIPPARCHUS_AETHENOVA_FINAL.pptx/.pdf` (6 pages) | assert in build script | — |
| Moving-object search (Planet X direction) | IN PROGRESS | — | — | HIPPARCHUS has not found Planet X |
| Machine-learning ranking | NOT IMPLEMENTED | — | — | No labelled data to train or test on fairly |
