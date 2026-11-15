#!/usr/bin/env bash
# Build one cut of the film:  ./scripts/build.sh [official|extended|vertical]   (default: official)
#   ambient WAV -> Remotion render (H.264 + AAC) -> two-pass loudnorm to -16 LUFS -> .srt
# Each cut's ambient track places its soft transitions on that cut's scene changes (CUTS, seconds).
set -euo pipefail
cd "$(dirname "$0")/.."
CUT=${1:-official}
case "$CUT" in
  official) ID=Hipparchus29; D=29.4; CUTS="3 7 15 18.5 20.3 22 26"; WAV=ambient.wav; CAP=src/captions.ts; OUT=../hipparchus_aethenova_29s ;;
  extended) ID=Extended; D=80.8; CUTS="5.8 11.8 17.6 23.6 29.3 37.0 44.6 51.7 58.5 64.9 71.3 77.4"; WAV=ambient_extended.wav; CAP=src/captions_extended.ts; OUT=../hipparchus_aethenova_extended ;;
  vertical) ID=Vertical; D=18; CUTS="4 7 10 14.5"; WAV=ambient_vertical.wav; CAP=src/captions_vertical.ts; OUT=../hipparchus_aethenova_vertical ;;
  *) echo "unknown cut: $CUT" >&2; exit 2 ;;
esac
D=$D CUTS="$CUTS" OUT=public/audio/$WAV ./scripts/make_ambient.sh
npx remotion render "$ID" out/raw_$CUT.mp4 --concurrency=4 --timeout=120000 --codec=h264 --crf=16 --audio-codec=aac --audio-bitrate=192k
# Pass 1 measures, pass 2 applies the measured values (linear mode); the picture is copied untouched.
M=$(ffmpeg -hide_banner -i out/raw_$CUT.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
g(){ echo "$M" | sed -n "s/.*\"$1\" : \"\([^\"]*\)\".*/\1/p"; }
ffmpeg -v error -y -i out/raw_$CUT.mp4 -c:v copy \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(g input_i):measured_TP=$(g input_tp):measured_LRA=$(g input_lra):measured_thresh=$(g input_thresh):offset=$(g target_offset):linear=true,aresample=48000" \
  -c:a aac -b:a 192k -movflags +faststart "$OUT.mp4"
node scripts/make_srt.mjs "$OUT.en.srt" "$CAP"
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate,sample_rate,channels -of compact "$OUT.mp4"
ffmpeg -hide_banner -i "$OUT.mp4" -af ebur128=peak=true -f null - 2>&1 | sed -n '/Summary/,$p'
