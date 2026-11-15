# Space Apps 2026 — portal submission texts (HIPPARCHUS, Team AETHENOVA)

Copy each block into the matching field. Check each field's character limit in the portal.

---

## Project name

HIPPARCHUS

## Team name

AETHENOVA

## Challenge

Planet X and SPHEREx

---

## High-level project summary

HIPPARCHUS answers a simple question with real NASA SPHEREx data: has this star really changed? It finds every
SPHEREx exposure of a position in the NASA/IPAC IRSA archive, checks each one (wavelength at the star, saturation and
quality flags, noise), compares only pairs that are truly comparable, measures the change with formal and systematic
errors, and then tries to break its own result. When a comparison cannot be trusted, it refuses and says why. On three
real targets it measured RW Aurigae 2.56× brighter in a year, refused Barnard's Star (saturated in all 58 epochs) and
found no significant change in WISE 0855−0714. As a first step towards Planet X, we validated a moving-object search on
three known asteroids, matching JPL Horizons to 0.15–0.18″ for (216) Kleopatra. HIPPARCHUS has not found Planet X.

---

## Link to project demo (video / slides)

- 29-second film: https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/#film
- Six-slide presentation (PDF): https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026/blob/main/presentation/HIPPARCHUS_AETHENOVA_FINAL.pdf

## Link to final project

https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/

## Link to code repository

https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026

---

## Detailed project description

**What it does.** SPHEREx maps the whole sky every six months in 102 infrared colours, which makes it a natural place
to look for things that change or move, out to a distant planet. But two SPHEREx images of the same star are rarely
directly comparable: the linear variable filters put the star at a different wavelength in each visit, bright stars
saturate, and zodiacal light changes with the season. Subtract two images naively and you get "variability" that is
only the instrument. HIPPARCHUS checks first, measures second, and then challenges its own result.

**How it works (Observe → Verify → Challenge → Explain).**
1. *Observe:* live IRSA SIA v2 search of SPHEREx DR1 and QR3; small server-side cutouts; a SHA-256 checksum for every
   archive answer and cutout.
2. *Verify:* for each epoch we subtract the zodiacal model, read the wavelength at the star, check 18 flag planes and the
   variance. Two epochs are compared only if they come from the same detector and differ by at most half a channel in
   wavelength; otherwise the pair is refused with a reason.
3. *Challenge:* the measurement is repeated with other apertures, sky annuli, masks, calibrations and wavelength rules,
   and with each pair left out (a "stability fingerprint"). A second, independent measurement fits the SPHEREx
   effective PSF to the native pixels (experimental).
4. *Explain:* each result comes with formal and systematic errors, refusal reasons, and an evidence file that rebuilds
   it and links every number back to its cutout checksum and dataset DOI.

**Results on real data.**
- RW Aurigae: 2.56× brighter in a year at 0.76 µm; 8 of 1540 pairs pass the checks; 175σ formal, about 12σ with a
  12.5% calibration floor; "≥1.5× at ≥5σ" holds in 24/24 analysis settings. RW Aur is a known variable young binary
  that SPHEREx does not resolve, so this is a measurement, not a discovery.
- Barnard's Star: comparison refused; 0 of 58 epochs usable because of saturation flags on the star.
- WISE 0855−0714: no significant change (27 valid pairs, largest 1.9σ); too faint to prove it is constant.

**Validation.** Blank-sky null tests (scatter 0.91, ideal 1); SIMULATED injection-recovery (44% at S/N 5, 99% at S/N 7);
control stars stay within ×0.86–1.07; SIMBAD and Gaia DR3 position matches. IRSA's own Source Discovery Tool, run
unmodified on the same exposures, gives RW Aur fluxes within 0.02% of ours and the same verdict on all 8 pairs, and
IRSA's Moving Object Search Tool lists the same 36 Kleopatra images we measured. Our pairing rule was also checked
against the spectral response it stands for. 183 automated tests (159 for the pipeline, most on real SPHEREx cutouts, and 24 for the animated scenes).

**What we found about the data.** Our audit against the official SPHEREx CWAVE/CBAND calibration showed that astropy
applies the celestial SIP distortion to the spectral lookup table, shifting wavelengths by up to 18 nm. We proved the
cause on 280 cutouts and added a corrected mode; no published conclusion changes. We also found that the SPHEREx
pipeline flags a moving asteroid as OUTLIER in 35 of 38 exposures, so static-star masks erase it.

**Towards Planet X.** A distant planet would appear as a source that moves between epochs. Before searching for unknown
movers we validated a blind moving-object search on the known asteroid (216) Kleopatra in 38 real SPHEREx exposures:
it was linked across 7 visits, and its positions match JPL Horizons computed from SPHEREx's own orbit to 0.15″/0.18″
rms; the fitted rates agree within 0.8σ. The same search, run blind, also found two more known asteroids: the fainter
(2052) Tamriko (0.54″/0.56″ rms, at the field-star measurement floor) and the fast near-Earth asteroid (433) Eros
(about 72″/h, 0.15″/0.20″ rms). SIMULATED movers at S/N ≥ 7 are recovered in 75–100% of trials. A second candidate
track in the Kleopatra field turned out to be two faint static stars and a detector hit, and we added a vetting step
that catches this. HIPPARCHUS has not found Planet X, and we do not claim it.

**Benefits.** Anyone can ask SPHEREx whether a star changed and get an answer that respects the instrument, or a clear
refusal with reasons. Every number is reproducible from public data.

**Reproducibility.** Each published case has a downloadable bundle (evidence, every cutout URL with its SHA-256,
settings, environment and a stand-alone checker), a one-page report and a notebook. Experimental work that did not pass
its pre-set rule (PSF-matched/ZOGY subtraction, a joint fit of RW Aur A and B, which SPHEREx cannot separate) is
documented and not used for any result.

**Tools.** Python (Astropy, NumPy, SciPy, reproject, astroquery, Matplotlib), FastAPI, React/TypeScript/Vite, Aladin
Lite, Manim, LaTeX, python-pptx, Remotion and FFmpeg for the film. MIT licence.

---

## Use of Artificial Intelligence (AI)

We used generative AI tools during the hackathon. The HIPPARCHUS and AETHENOVA logos are AI-generated, and every
published copy carries a visible "AI-generated" mark. An AI coding assistant helped write and refactor code, tests and
build scripts, and helped assemble the video (whose footage is real screen recordings of our app and real SPHEREx
images; illustration scenes are labelled). AI also helped review methods, check references and draft text for the
README, report and slides. AI did not produce any measurement and did not validate the science: every number comes from
running our code on real SPHEREx images, and validation is our automated tests, null tests, SIMULATED
injection-recovery tests and stability checks. We reviewed and ran all code and are responsible for every claim.

---

## NASA data

- SPHEREx DR1 Spectral Images, NASA/IPAC Infrared Science Archive (IRSA), doi:10.26131/IRSA678
- SPHEREx Quick Release QR3 Spectral Images, NASA/IPAC IRSA, doi:10.26131/IRSA662
- SPHEREx Spectral WCS calibration (CWAVE/CBAND), cal-swcs-v5-2026-191, via IRSA
- JPL Horizons ephemerides (observer: SPHEREx) and JPL Small-Body Identification API
- AllWISE and 2MASS catalogues (via IRSA/VizieR), used only to identify static sources

## Space agency partner and other data

- ESA Gaia DR3 (Gaia Collaboration 2023, doi:10.1051/0004-6361/202243940), used only to check positions and identify
  field stars
- SIMBAD (CDS, Strasbourg), used only for target identification

## References

- Doré et al. 2014, Cosmology with the SPHEREx All-Sky Spectral Survey, arXiv:1412.4872
- Hui et al. 2026, Spectral Response of SPHEREx, ApJS, doi:10.3847/1538-4365/ae522c
- Zackay, Ofek & Gal-Yam 2016, Proper Image Subtraction, doi:10.3847/0004-637X/830/1/27
- Rodriguez et al. 2013, RW Aur A occultation, doi:10.1088/0004-6256/146/5/112
- Luhman 2014, WISE 0855−0714, doi:10.1088/2041-8205/786/2/L18
- Trujillo & Sheppard 2014, doi:10.1038/nature13156; Batygin & Brown 2016, doi:10.3847/0004-6256/151/2/22
- Astropy Collaboration 2013/2018/2022; NumPy (Harris et al. 2020); SciPy (Virtanen et al. 2020)
- IRSA SPHEREx archive documentation and tutorials: https://caltech-ipac.github.io/spherex-archive-documentation/
- Full bibliography: report/HIPPARCHUS_AETHENOVA_REFERENCES.bib in the repository

## Tags

#SPHEREx #PlanetX #infrared #variability #timedomain #asteroids #reproducibility #openscience #astropy
