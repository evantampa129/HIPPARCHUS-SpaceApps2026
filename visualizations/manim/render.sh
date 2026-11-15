#!/usr/bin/env bash
# Render every scene at 1080p30, export an H.264 MP4 and a PNG still to renders/,
# web copies (<= 2 MB) and poster PNGs to docs/media/manim/, then write MANIFEST.json.
#   ./render.sh            all scenes
#   ./render.sh m04        only scenes whose file name starts with m04
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PY="$HERE/.venv/bin/python"
MANIM="$HERE/.venv/bin/manim"
WEB="$ROOT/docs/media/manim"
ONLY=${1:-}
mkdir -p "$HERE/renders" "$WEB"

mapfile -t SCENES < <(cd "$HERE/scenes" && "$PY" -c 'from registry import SCENES; print("\n".join(f"{m}:{c}" for m, c in SCENES))')

for s in "${SCENES[@]}"; do
  file=${s%%:*}; cls=${s##*:}
  [[ -n $ONLY && $file != $ONLY* ]] && continue
  echo "== $file ($cls)"
  (cd "$HERE/scenes" && "$MANIM" render --resolution 1920,1080 --frame_rate 30 --disable_caching \
      --media_dir "$HERE/media" -v WARNING --progress_bar none -o "$cls" "$file.py" "$cls")
  src="$HERE/media/videos/$file/1080p30/$cls.mp4"
  out="$HERE/renders/$file.mp4"
  # We re-encode once with settings every browser plays: H.264, yuv420p, no audio, moov atom first.
  ffmpeg -y -loglevel error -i "$src" -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
      -movflags +faststart -an "$out"
  # The still is taken just before the end, when every element is on screen.
  ffmpeg -y -loglevel error -sseof -0.25 -i "$out" -frames:v 1 -update 1 "$HERE/renders/$file.png"
  # Web copy: 720p; we raise the CRF until it fits in 2 MB.
  for crf in 26 29 32 35; do
    ffmpeg -y -loglevel error -i "$out" -vf scale=1280:-2 -c:v libx264 -preset slow -crf $crf \
        -pix_fmt yuv420p -movflags +faststart -an "$WEB/$file.mp4"
    (( $(stat -c %s "$WEB/$file.mp4") <= 2000000 )) && break
  done
  ffmpeg -y -loglevel error -sseof -0.25 -i "$out" -frames:v 1 -update 1 -vf scale=1280:-2 "$WEB/${file}_poster.png"
done

"$PY" "$HERE/tools/make_manifest.py"
