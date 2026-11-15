#!/usr/bin/env bash
# Stage the public demo and (optionally) push it to a Hugging Face Docker Space.
#
#   deploy/deploy_space.sh                 # stage only, into deploy/.space
#   deploy/deploy_space.sh --build         # stage and build/run-test the image locally
#   deploy/deploy_space.sh --push USER/hipparchus
#
# --push needs the `hf` CLI logged in (`hf auth login`, a write token). The Space
# is created public on free CPU hardware ("cpu-basic"), which costs nothing.
# Only an explicit allowlist is copied: no cutout cache, no slides, no report,
# no video, no .env, and nothing that is not already in the public repository.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/deploy/.space"
rm -rf "$OUT" && mkdir -p "$OUT"

copy() { mkdir -p "$OUT/$(dirname "$1")" && cp -r "$ROOT/$1" "$OUT/$1"; }
for f in LICENSE backend/pyproject.toml backend/hipparchus data/manifests \
         submission/evidence/robustness.json \
         frontend/index.html frontend/package.json frontend/package-lock.json \
         frontend/tsconfig.json frontend/vite.config.ts frontend/src \
         deploy/constraints.txt; do
  copy "$f"
done
cp "$ROOT/deploy/Dockerfile" "$OUT/Dockerfile"
cp "$ROOT/deploy/.dockerignore" "$OUT/.dockerignore"
cp "$ROOT/deploy/space_README.md" "$OUT/README.md"
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
# Last check: nothing secret-looking or large slipped in.
if find "$OUT" \( -name '.env*' -o -name '*.pem' -o -name '*.key' -o -name '*.fits' \) | grep -q .; then
  echo "refusing: secret-like or FITS file in staging" >&2; exit 1
fi
echo "staged $(find "$OUT" -type f | wc -l) files, $(du -sh "$OUT" | cut -f1) in $OUT"

case "${1:-}" in
  --build)
    docker build -t hipparchus-space "$OUT"
    echo "run: docker run --rm -p 7860:7860 hipparchus-space   then open http://localhost:7860" ;;
  --push)
    REPO="${2:?usage: --push USER/SPACE}"
    # cpu-basic is the free tier; never pass a paid --flavor here.
    hf repos create "$REPO" --type space --sdk docker --public --exist-ok
    hf upload "$REPO" "$OUT" . --repo-type space --commit-message "Deploy public demo"
    echo "https://huggingface.co/spaces/$REPO" ;;
esac
