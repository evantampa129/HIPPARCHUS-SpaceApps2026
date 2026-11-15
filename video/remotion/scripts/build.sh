#!/usr/bin/env bash
# Full build of the deliverable (see the comment block at the top of src/hipparchus.tsx).
#   ambient WAV -> Remotion render (H.264 + AAC) -> two-pass loudnorm to -16 LUFS -> .srt
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=../hipparchus_aethenova_29s.mp4
./scripts/make_ambient.sh
npx remotion render Hipparchus29 out/raw.mp4 --concurrency=4 --timeout=120000 --codec=h264 --crf=16 --audio-codec=aac --audio-bitrate=192k
# Pass 1 measures, pass 2 applies the measured values (linear mode); the picture is copied untouched.
M=$(ffmpeg -hide_banner -i out/raw.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
g(){ echo "$M" | sed -n "s/.*\"$1\" : \"\([^\"]*\)\".*/\1/p"; }
ffmpeg -v error -y -i out/raw.mp4 -c:v copy \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(g input_i):measured_TP=$(g input_tp):measured_LRA=$(g input_lra):measured_thresh=$(g input_thresh):offset=$(g target_offset):linear=true,aresample=48000" \
  -c:a aac -b:a 192k -movflags +faststart "$OUT"
node scripts/make_srt.mjs ../hipparchus_aethenova_29s.en.srt
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate,sample_rate,channels -of compact "$OUT"
ffmpeg -hide_banner -i "$OUT" -af ebur128=peak=true -f null - 2>&1 | sed -n '/Summary/,$p'
