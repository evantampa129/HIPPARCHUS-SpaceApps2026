---
title: HIPPARCHUS
emoji: 🔭
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: SPHEREx epoch-to-epoch change checks, live from IRSA
---

Interactive version of HIPPARCHUS: search any position in the SPHEREx DR1/QR3
archive at IRSA, download the cutouts, run the quality checks and compare
epochs. Everything is read-only and uses public NASA data.

The first analysis of a position downloads its cutouts and takes 1-4 minutes;
after that it is cached. If IRSA is slow or returns errors, the saved listing
for the preset targets is used and labelled as cached.

This is a shared free server, so it has limits: a few analyses per visitor per
hour, at most two running at once, and at most 60 epochs per analysis. If you
see "busy" or "too many requests", wait a minute and try again.

Static results page (no limits): https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/
Source: https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026
