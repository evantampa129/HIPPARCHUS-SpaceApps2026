# Public release audit

Checked on 16 Nov 2026. Every line below comes from a command we ran on that date; nothing is assumed.

## Commits

| | Commit | Notes |
|---|---|---|
| Public repo `evantampa129/HIPPARCHUS-SpaceApps2026`, branch `main` | `fcdd112` (code and results); this file is added in the next commit | 25 commits pushed in order, no force-push, no history rewrite |
| Private working repo, branch `final-aethenova` | `ac5d6e2` | Stays private. The public tree equals this commit minus four files we do not publish (three team logo images and an internal deployment plan) |

Repository visibility was not changed: the public repo is PUBLIC, the private one is PRIVATE (checked with `gh repo view`).

## Links and HTTP checks

| URL | Result |
|---|---|
| https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/ (Judge Mode) | 200; GitHub Pages build `built` for `fcdd112` |
| Judge Mode film `media/hipparchus_aethenova_29s.mp4` | 200, 7.4 MB |
| Film poster, Manim scenes M01 and M06 on the page | 200 |
| Page sections `#rw_aur #barnard #wise0855 #motion #psfsub #explorers #scenes #reproduce #film` | all present |
| `submission/FEATURE_AUDIT.json`, `FINAL_IMPLEMENTATION_CHECKLIST.md`, report PDF, film (raw.githubusercontent.com) | 200 |

Public interactive app: **not hosted**. The Docker image builds and runs locally; the home page, health, explorer, reproduction-bundle and mini-report routes all answer 200 inside the container. Pushing it to Hugging Face failed with HTTP 402: Docker Spaces now need a paid plan, and we keep the project at zero cost. Judge Mode on GitHub Pages is the public demo; the README shows how to run the image.

## Deliverables

| Item | Measured |
|---|---|
| Automated tests | 183 collected, 183 passed: 159 backend (`pytest`, 1 min 51 s) and 24 Manim scene tests (4 min 13 s) |
| Frontend | `npm run build` clean |
| Report `report/HIPPARCHUS_AETHENOVA_FINAL.pdf` | 18 pages, XeLaTeX, no undefined references |
| Deck `presentation/HIPPARCHUS_AETHENOVA_FINAL.pptx/.pdf` | 6 slides / 6 pages |
| Film `video/hipparchus_aethenova_29s.mp4` | 29.418 s, H.264 1920×1080 30 fps, AAC 48 kHz stereo, −15.7 LUFS; English captions `.en.srt` |
| Feature audit | 30 features: 22 IMPLEMENTED_AND_VERIFIED, 4 IMPLEMENTED_EXPERIMENTAL, 1 PARTIALLY_IMPLEMENTED, 1 BLOCKED_BY_EXTERNAL_SERVICE, 2 NOT_IMPLEMENTED |

## Secrets and sensitive content

Scanned the whole public tree and the contents of every bundle zip for access tokens (GitHub, Hugging Face, AWS, generic `sk-`), private keys, passwords and personal e-mail addresses: none found. One pattern hit was a fragment of base64 image data in a mini report, not a key. Three entries in `submission/evidence/wavecal_check.json` record the absolute local path of a cached calibration file; they reveal only the GitHub user name and were already public before this release.

## Scientific issues still open

- RW Aur A and B are not resolved by SPHEREx (6.15″ pixels); the joint fit confirms they cannot be separated. The ×2.56 change is for the pair.
- ePSF photometry and PSF-matched subtraction stay experimental: χ²_ν well above 1 on bright cores, and no subtraction method passed the rule we set before running it.
- Moving objects are validated on three known asteroids only. Track vetting removes static stars and detector hits but not chance alignments of 3–4 single detections; a false-alarm estimate is not built. HIPPARCHUS has not found Planet X.
- Published numbers use the legacy wavelength source for reproducibility; the corrected CWAVE source changes no conclusion.

## External service failures

- IRSA SIA answered HTTP 502 for the whole benchmark run, so the 32-object held-out benchmark has no star metrics yet (asteroids 3/3 measured; 3 Y dwarfs did not resolve in Sesame). It resumes from cache with `python scripts/run_benchmark.py --online`.
- IRSA also returned 502 during the film's screen recording; the app's cached listing is shown and labelled as cached.

## Not done by this release

A push to GitHub is not a Space Apps portal submission. The portal submission is an action the team takes itself.
