# Public demo image: builds the web page, then serves it with the API from one
# uvicorn process. Built from the staging folder made by deploy/deploy_space.sh,
# which copies only the files listed there (no cutout cache, no secrets).

FROM node:20-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/mpl HOME=/tmp \
    HIPPARCHUS_PUBLIC=1
# Spaces run the container as uid 1000; give that user the data folder (cache,
# saved archive listings) and nothing else.
RUN useradd -m -u 1000 app
WORKDIR /app
COPY deploy/constraints.txt /tmp/constraints.txt
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/hipparchus backend/hipparchus
RUN pip install -c /tmp/constraints.txt -e backend
COPY data/manifests data/manifests
COPY submission/evidence/robustness.json submission/evidence/robustness.json
COPY --from=web /src/frontend/dist frontend/dist
RUN mkdir -p data/cache && chown -R app:app data
USER app
EXPOSE 7860
# --limit-concurrency caps open connections before they reach the app; the
# per-route limits live in hipparchus/guard.py.
CMD ["uvicorn", "hipparchus.serve:app", "--host", "0.0.0.0", "--port", "7860", \
     "--limit-concurrency", "64", "--timeout-keep-alive", "15", "--no-server-header"]
