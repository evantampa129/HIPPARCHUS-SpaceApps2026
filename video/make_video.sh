#!/usr/bin/env bash
# Cut the screen recording of the real app into the <30 s demo, with English captions burned in.
# Usage: ./make_video.sh <recording.webm> <title.png> <end.png>
# Times below match the recording made on 2026-11-15; a new recording needs new cut points.
set -euo pipefail
cd "$(dirname "$0")"
F=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
cap(){ printf "drawtext=fontfile=%s:text='%s':x=(w-text_w)/2:y=h-62:fontsize=28:fontcolor=white:box=1:boxcolor=0x0b1020CC:boxborderw=12:enable='between(t\\,%s\\,%s)'" "$F" "$1" "$2" "$3"; }
# Constant 30 fps first, so the trims below are exact.
ffmpeg -v error -y -i "$1" -vf fps=30 -c:v libx264 -preset veryfast -crf 18 /tmp/rec30.mp4
ffmpeg -v error -y -loop 1 -framerate 30 -t 3 -i "$2" -i /tmp/rec30.mp4 -loop 1 -framerate 30 -t 4 -i "$3" -filter_complex "\
[1:v]split=3[r1][r2][r3];[0:v]format=yuv420p,setsar=1[t];\
[r1]trim=1:3.5,setpts=PTS-STARTPTS,format=yuv420p,setsar=1,$(cap 'Type a position or pick a star\: we query the IRSA archive live' 0 3)[s1];\
[r2]trim=38.5:41,setpts=PTS-STARTPTS,format=yuv420p,setsar=1,$(cap 'Live IRSA answer. One release was down (502)\: labelled PARTIAL' 0 3)[s2];\
[r3]trim=41:59.3,setpts=(PTS-STARTPTS)/1.25,fps=30,format=yuv420p,setsar=1,$(cap 'Every epoch is quality-checked and matched in wavelength' 0 4.5),$(cap 'Blink and difference\: RW Aur 2.6x brighter, control star stable' 4.5 8),$(cap 'Barnard’s Star saturates SPHEREx\: comparison refused' 8 15)[s3];\
[2:v]format=yuv420p,setsar=1[e];[t][s1][s2][s3][e]concat=n=5:v=1:a=0[out]" \
  -map "[out]" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -movflags +faststart hipparchus_demo_30s.mp4
