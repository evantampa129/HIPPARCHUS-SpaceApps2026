# Data provenance

**Where the images come from.** All images are SPHEREx Level-2 spectral images from the NASA/IPAC Infrared Science
Archive (IRSA). We use two releases: DR1 (doi:10.26131/IRSA678) and QR3 (doi:10.26131/IRSA662). We find them with
IRSA's SIA v2 service (`https://irsa.ipac.caltech.edu/SIA`, collections `spherex_dr1` and `spherex_qr3`) and download
0.05° server-side cutouts through the `?center=…&size=…` interface on each image URL.

**What we keep.**
- `data/manifests/` holds every archive answer, with the SHA-256 of the raw response.
- `submission/evidence/*.json` lists, for every epoch, the observation ID, release, DOI, detector, exposure times,
  cutout URL and cutout SHA-256, along with the settings and outputs of every comparison.
- `submission/evidence/graph_*.json` links each result to its cutout, its archive answer and the dataset DOI. A test
  fails if any link is broken.

**What we do not redistribute.** The FITS cutouts themselves stay in a local cache (`data/cache/`, not in git), since
anyone can download them again from IRSA. The only exception is three small cutouts under `backend/tests/fixtures/`,
which the tests need offline.

**Rebuilding everything.** `backend/scripts/reproduce_*.py` downloads the same cutouts, checks their checksums and
rewrites the evidence files. If IRSA has reprocessed an image, the checksum changes and the script says so.

**Catalogues.** We use SIMBAD and Gaia DR3 only to check that each target position is on the right star. Gaia DR3 is
queried through IRSA's copy, and SIMBAD through the CDS mirrors that CDS recommended after its November 2026 outage.
These checks are recorded in `submission/evidence/catalog_match.json`.

**Synthetic data.** Any synthetic source injected into a real image for testing is labelled SIMULATED in code, output
and figures. No SIMULATED source is used in any science result.
