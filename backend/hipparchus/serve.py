"""One process for a demo: the API under /api and the built web page at /.

Run after `npm run build` in frontend/:
    uvicorn hipparchus.serve:app --port 8080
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from hipparchus.api import app as api_app

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(title="HIPPARCHUS demo")
# Same /api prefix the Vite dev proxy uses, so the page works unchanged in both setups.
app.mount("/api", api_app)
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")

# Public, no-login hosting (e.g. a free Docker Space): rate limits, a cap on
# concurrent analyses, timeouts, input checks and cache eviction. Opt-in, so
# local runs and the tests are unchanged. See hipparchus/guard.py.
if os.environ.get("HIPPARCHUS_PUBLIC") == "1":
    from hipparchus import api, archive, cutouts
    from hipparchus.guard import PublicGuard

    app = PublicGuard(
        app, cache_dir=cutouts.CACHE_DIR, manifest_dir=archive.MANIFEST_DIR,
        # The preset targets' saved listings are the fallback when IRSA is down.
        protected_manifests={archive._manifest_path(t["ra"], t["dec"]).name for t in api.TARGETS},
        results=api._RESULTS, results_lock=api._LOCK)
