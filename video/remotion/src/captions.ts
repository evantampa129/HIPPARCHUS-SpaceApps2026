// The narration text. There is no voice recording: these lines are burned into the picture
// and written to ../hipparchus_aethenova_29s.en.srt by scripts/make_srt.mjs (same source,
// so the two never drift). Times in ms on the 29.4 s timeline.
export type Cue = { text: string; startMs: number; endMs: number };

export const CUES: Cue[] = [
  { startMs: 300, endMs: 3900, text: "For two thousand years, we have charted the sky and asked what changes." },
  { startMs: 4200, endMs: 7900, text: "SPHEREx now maps the whole sky in infrared light, again and again." },
  { startMs: 8200, endMs: 11900, text: "RW Aurigae, a year apart. But wavelength and noise can fake a change." },
  { startMs: 12200, endMs: 17900, text: "HIPPARCHUS searches the archive, checks each epoch, compares like with like." },
  { startMs: 18100, endMs: 21300, text: "RW Aur: 2.56× brighter. The change holds in 24 of 24 analysis settings." },
  { startMs: 21400, endMs: 23900, text: "Barnard’s Star is saturated: comparison refused." },
  { startMs: 24100, endMs: 26950, text: "Asteroid Kleopatra, tracked in real SPHEREx images, matches JPL Horizons. No Planet X." },
];
