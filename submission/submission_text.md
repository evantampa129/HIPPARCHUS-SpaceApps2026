# HIPPARCHUS: text for the Space Apps project page

Fields in the order of the 2026 Project Submission Guide (spaceappschallenge.org, 13 Nov 2026).
Every field below is ready to paste.

---

## Project Name
HIPPARCHUS: has this star changed?

## High-Level Project Summary
HIPPARCHUS is a web tool that answers "has this star changed?" using real NASA SPHEREx images, and refuses to answer
when the data cannot support it. For any sky position it queries the NASA/IPAC IRSA archive live, downloads every
SPHEREx DR1/QR3 exposure as a small FITS cutout and checks each one. The checks remove zodiacal light, read the
wavelength at the star (SPHEREx's filters change wavelength across the detector), and look at 18 pipeline quality
flags and the noise. It then compares only pairs seen at the same wavelength. On real data it measures RW Aurigae
2.5 times brighter after one year while a control star stays constant. It refuses saturated Barnard's Star with clear
reasons, and reports no detectable change for the faint brown dwarf WISE 0855. Every result comes with a reproducible
evidence file.

## Link to Project Demo
https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026/blob/main/video/hipparchus_demo_30s.mp4
(26.6 s screen recording of the real app, English captions burned in. The 7 slides are at
https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026/blob/main/presentation/hipparchus_7_slides.pdf)

## Link to Final Project
https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026

## Detailed Project Description
**What it does.** You enter coordinates or pick a preset star, and the tool:
1. Searches the IRSA image service (SIA v2) for SPHEREx DR1 and QR3 science exposures. It records the SHA-256 of each
   archive answer and labels the result LIVE, PARTIAL (one release unreachable) or CACHED (archive offline, last
   complete listing).
2. Downloads 0.05° FITS cutouts and verifies their checksum every time they are reused.
3. Checks each epoch: it subtracts the pipeline zodiacal-light model, finds the star with the WCS, and reads its
   wavelength and channel width from the spectral WCS. It rejects the epoch if any of 18 flag planes (OVERFLOW,
   NONLINEAR, TRANSIENT, PERSIST, ...) touches the star, or if values or variance are missing.
4. Pairs epochs only if both are usable, come from the same detector, and differ in wavelength by no more than half a
   channel. Every other pair is refused, and each refusal comes with a stated reason.
5. Compares each valid pair: it reprojects one epoch onto the other's grid and does aperture photometry with sky
   annulus and full error propagation. It reports flux ratio and significance, a per-pixel significance map, the
   centroid shift, and a control-star check in the same images.
6. Shows everything in a web app: a timeline of epochs on real dates, chronological playback, a blink comparison,
   difference and significance maps, quality issues per epoch, links to the original IRSA files and dataset DOIs, and
   a download of the full evidence file.

**Results on real data (15 Nov 2026):**

| Target | Epochs | Usable epochs | Valid pairs | Result |
|---|---|---|---|---|
| RW Aurigae (D1) | 56 | 18 | 8 | All 8 pairs brighter later; strongest ×2.56 over 371 days (175σ formal); control star ×0.86–1.07, ≤2.2σ |
| Barnard's Star (D6) | 58 | 0 | 0 | Saturated in every epoch, so the comparison is refused |
| WISE 0855−0714 (D6) | 45 | 37 | 27 | No change above 1.9σ; spread of significances 0.83, so the error bars hold up |

RW Aur is a known variable young star. We report a measurement, not a discovery.

**Benefits.** Turns SPHEREx's repeated all-sky imaging into a time-domain tool that a student or citizen scientist
can trust, because it says when it cannot answer. This is the first step towards searching for moving objects
(Planet X-like) and variable sources in SPHEREx data.

**Tools.** Python 3.12, FastAPI, Astropy, NumPy, SciPy, reproject, Matplotlib; React 18 + TypeScript + Vite; pytest
(23 tests on real SPHEREx cutouts); LaTeX for the technical report. Source code is under the MIT licence.

**Validation.** A null test at blank positions in the real image pairs gives significances with spread 0.91
(1 would be exact, n=93, none beyond 3σ), so the error bars are right or conservative. Injection-recovery with
SIMULATED stars (kept apart from the real results) finds 44% at S/N 5, 87% at 6 and 99% at 7, as expected for a 5σ
threshold. An evidence graph links every result to its cutout checksum, archive answer and dataset DOI, with no
broken links. Plotting brightness against wavelength shows the RW Aur brightening directly. With cached cutouts one
target takes about a minute; image requests answer in 30 ms (p50).

**Reproducibility.** `backend/scripts/reproduce_evidence.py` rebuilds every result in `submission/evidence/`,
`backend/scripts/reproduce_validation.py` the validation checks, and `report/reproduce_report.sh` the figures and the
7-page technical report
(`report/hipparchus_scientific_report.pdf`).

## NASA Data
- SPHEREx Data Release 1 Spectral Images, NASA/IPAC IRSA, doi:10.26131/IRSA678
- SPHEREx Quick Release 3 Spectral Images, NASA/IPAC IRSA, doi:10.26131/IRSA662
- IRSA Simple Image Access v2 service: https://irsa.ipac.caltech.edu/SIA

## Space Agency Partner Data and Other References
- Doré et al. 2014, "Cosmology with the SPHEREx All-Sky Spectral Survey", arXiv:1412.4872
- Rodriguez et al. 2013, AJ 146, 112, doi:10.1088/0004-6256/146/5/112 (RW Aur variability)
- Luhman 2014, ApJL 786, L18, doi:10.1088/2041-8205/786/2/L18 (WISE 0855−0714)
- Software: Astropy (A&A 558, A33; AJ 156, 123; ApJ 935, 167), NumPy (Nature 585, 357), SciPy (Nat. Methods 17, 261),
  Matplotlib (CiSE 9, 90), reproject (Astropy project)
- No external catalogue (SIMBAD, Gaia) was used: they were unreachable during the hackathon, so star positions are
  approximate priors and the stars are measured in the images.

## Use of Artificial Intelligence (AI)
I used AI tools mainly for the graphics: the logos, which carry a visible "AI-generated" watermark, and putting
together the demo video. I also used them to cross-check the NASA/IRSA dataset references and as a coding assistant.
I ran and tested all the code myself. The data, measurements and results all come from real SPHEREx images, and the
idea is my own.

## Team
Team AITHENOVA. Member: Evangelos Tampachaniotis (single-member team).
