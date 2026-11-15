# Public release audit

Checked on 17 Nov 2026. Every line below comes from a command we ran on that date; nothing is assumed. The previous audit (16 Nov, public commit `fcdd112`) is in the git history of this file.

## Commits

| | Commit | Notes |
|---|---|---|
| Public repo `evantampa129/HIPPARCHUS-SpaceApps2026`, branch `main` | the commit before this file (code and results) | Eleven new commits on top of the previous `main` |
| Private working repo, branch `final-aethenova` | same content | Stays private. The public tree equals it minus four files we do not publish (three team logo images and an internal deployment plan) |

Repository visibility was not changed (checked with `gh repo view` after the push).

## Links and HTTP checks

Filled in after the push; see the commit that follows this file for the Pages build result.

| URL | Expected |
|---|---|
| https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/ (Judge Mode) | 200 |
| `media/hipparchus_aethenova_29s.mp4`, `_extended.mp4`, `_vertical.mp4` | 200 (8.2 MB, 14.9 MB, 4.5 MB) |

Public interactive app: **not hosted**. Free plans were measured against the app (187 MiB idle, about 350 MiB after two analyses, first analysis about 7 min because it downloads SPHEREx images); the free tiers that fit sleep and lose their disk, the others need a card or a paid plan. Judge Mode on GitHub Pages stays the public demo; the README shows how to run the Docker image.

## Deliverables

| Item | Measured |
|---|---|
| Automated tests | 194 passed: 159 backend (`pytest`) and 35 Manim scene tests |
| Frontend | `npm run build` clean |
| Report `report/HIPPARCHUS_AETHENOVA_FINAL.pdf` | 19 pages, XeLaTeX, no undefined references; new section on the held-out benchmark |
| Deck `presentation/HIPPARCHUS_AETHENOVA_FINAL.pptx/.pdf` | 6 slides / 6 pages; slide 5 carries the benchmark line |
| Official film `video/hipparchus_aethenova_29s.mp4` | 29.418 s, H.264 1920×1080 30 fps, AAC 48 kHz stereo, −15.7 LUFS, 7 captions |
| Extended film `video/hipparchus_aethenova_extended.mp4` | 80.81 s, 1920×1080, −15.9 LUFS, 12 captions |
| Vertical film `video/hipparchus_aethenova_vertical.mp4` | 18.0 s, 1080×1920, −16.0 LUFS, 4 captions |
| Manim scenes | M01–M15; M07 labelled SIMULATED, M15 labelled CONCEPTUAL |
| Feature audit | 30 features: 23 IMPLEMENTED_AND_VERIFIED, 4 IMPLEMENTED_EXPERIMENTAL, 1 PARTIALLY_IMPLEMENTED, 2 NOT_IMPLEMENTED |

## Held-out benchmark (real SPHEREx data, rule |σ| ≥ 5 fixed before the run)

- Known variables: 3/3 found (AA Tau, DG Tau, V2492 Cyg).
- Stable stars: 2 of 4 with valid pairs flagged (P177D, G191-B2B), from 5 of 248 stable pairs (2.0%, object bootstrap 0–4.1%). All five are 6.5–8.7% changes at 5–7σ, below the 12.5% calibration floor measured earlier; formal errors miss that systematic. Two P177D pairs share one exposure.
- Photometric bias on stable pairs: −1.0% (bootstrap −1.5% to −0.4%).
- No saturated star fell in the held-out split; in the other splits 5/5 were refused.
- Thresholds were not changed after seeing these results. The floor check is reported as secondary only.

## Secrets and sensitive content

Scanned the whole public tree and the contents of every bundle zip for access tokens (GitHub, Hugging Face, AWS, generic `sk-`), private keys and personal e-mail addresses: none found. The three unlabelled team logos and the internal deployment plan are not in the public tree.

## Scientific issues still open

- RW Aur A and B are not resolved by SPHEREx (6.15″ pixels); the ×2.56 change is for the pair.
- Formal errors are too small on stable stars (spread 1.8 instead of 1); the benchmark false alarms come from this.
- ePSF photometry and PSF-matched subtraction stay experimental.
- Moving objects are validated on known asteroids only; HIPPARCHUS has not found Planet X.

## External service failures

- On 17 Nov a benchmark run hit 8 IRSA SIA HTTP 503 errors and 2 DNS failures; the next run recovered all of them.
- IRSA returned 502 during the film's screen recording; the app's cached listing is shown and labelled as cached.

## Not done by this release

A push to GitHub does not change an entry already submitted to the Space Apps portal. The portal submission is an action the team takes itself.
