// The narration text. There is no voice recording: these lines are burned into the picture
// and written to ../hipparchus_aethenova_29s.en.srt by scripts/make_srt.mjs (same source,
// so the two never drift). Times in ms on the 29.4 s timeline.
export type Cue = { text: string; startMs: number; endMs: number };

export const CUES: Cue[] = [
  { startMs: 300, endMs: 2900, text: "RW Aurigae in two real SPHEREx images, a year apart. Is this change real?" },
  { startMs: 3200, endMs: 6900, text: "A different wavelength can fake a change, so pairs too far apart are refused." },
  { startMs: 7200, endMs: 14800, text: "HIPPARCHUS searches the archive, checks every exposure and compares like with like." },
  { startMs: 15100, endMs: 18400, text: "RW Aur got 2.56× brighter: 175σ formally, still 12.4σ with a 12.5% calibration floor." },
  { startMs: 18600, endMs: 20200, text: "The change holds in 24 of 24 analysis settings." },
  { startMs: 20400, endMs: 21900, text: "Barnard’s Star saturates SPHEREx: comparison refused." },
  { startMs: 22100, endMs: 25900, text: "Asteroid Kleopatra, tracked in real SPHEREx images, matches JPL Horizons. No Planet X." },
];
