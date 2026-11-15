#!/usr/bin/env bash
# Ambient bed for the 29.4 s video, synthesised with ffmpeg only (no samples, no music library):
# a slow A-minor drone (sine partials with independent tremolo), filtered pink noise as "air",
# a soft swell at every scene cut and a quiet high shimmer under the final identity.
# Output: public/audio/ambient.wav (48 kHz stereo). Loudness is set on the final mix, not here.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p public/audio
D=29.4
# Drone: partials of A (110 Hz) and E, each breathing at its own slow rate.
DRONE="0.22*sin(2*PI*110*t)*(0.65+0.35*sin(2*PI*0.07*t))\
+0.14*sin(2*PI*164.81*t+0.4)*(0.5+0.5*sin(2*PI*0.05*t+1.3))\
+0.10*sin(2*PI*220.4*t)*(0.55+0.45*sin(2*PI*0.09*t+2.1))\
+0.05*sin(2*PI*329.6*t+1.1)*(0.5+0.5*sin(2*PI*0.13*t))\
+0.03*sin(2*PI*130.81*t)*(0.5+0.5*sin(2*PI*0.04*t+0.5))"
# Swells at the scene cuts (4, 8, 12, 18, 24, 27 s): short gaussian bumps of a fifth.
SW=""
for c in 4 8 12 18 24 27; do
  SW="$SW+0.07*exp(-pow(t-$c,2)/0.35)*(sin(2*PI*440*t)+0.6*sin(2*PI*659.26*t))"
done
# Shimmer for the final identity (from 26.5 s), fading with the picture.
SH="+0.025*clip(t-26.5,0,1)*(sin(2*PI*880*t)*(0.5+0.5*sin(2*PI*3*t))+0.6*sin(2*PI*1318.5*t+1))"
ffmpeg -v error -y \
  -f lavfi -i "aevalsrc='(${DRONE})${SW}${SH}|(${DRONE//t+0.4)/t+0.9)})${SW}${SH}':s=48000:d=$D" \
  -f lavfi -i "anoisesrc=color=pink:amplitude=0.12:d=$D:r=48000" \
  -filter_complex "[1]bandpass=f=900:width_type=o:w=2,lowpass=f=3000,aformat=channel_layouts=stereo,volume=0.35[n];\
[0][n]amix=inputs=2:normalize=0,lowpass=f=5000,highpass=f=60,afade=t=in:d=2.0,afade=t=out:st=27.6:d=1.8,\
aecho=0.6:0.5:180|320:0.25|0.18,atrim=0:$D" \
  -c:a pcm_s16le public/audio/ambient.wav
ffprobe -v error -show_entries format=duration -of csv=p=0 public/audio/ambient.wav
