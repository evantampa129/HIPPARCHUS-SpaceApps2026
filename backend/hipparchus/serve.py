"""One process for a demo: the API under /api and the built web page at /.

Run after `npm run build` in frontend/:
    uvicorn hipparchus.serve:app --port 8080
"""

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
