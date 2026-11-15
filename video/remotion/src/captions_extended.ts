// Burned-in captions of the extended film; also written to ../hipparchus_aethenova_extended.en.srt.
// Times in ms, computed from the same clip lengths as src/extended.tsx.
import type { Cue } from "./captions";

export const CUES_EXTENDED: Cue[] = [
  { startMs: 200, endMs: 5566, text: "RW Aurigae in two real SPHEREx images, a year apart, 2.56× brighter. Is this change real?" },
  { startMs: 6300, endMs: 11633, text: "Each visit sees the star at a slightly different wavelength. Close pairs are compared; the rest are refused." },
  { startMs: 12366, endMs: 17400, text: "The image's own WCS maps every pixel to right ascension and declination, so both images measure the same star." },
  { startMs: 18133, endMs: 23366, text: "Aperture photometry sums the star's real pixels and subtracts the local sky." },
  { startMs: 24100, endMs: 29133, text: "A PSF model fitted on the native pixels cross-checks the aperture. It is still experimental." },
  { startMs: 29866, endMs: 36800, text: "The working app does this on demand: archive search, quality checks, timeline and comparison." },
  { startMs: 37533, endMs: 44366, text: "Formal errors give 175σ. With the 12.5% calibration floor it is 12.4σ, still above our 5σ rule." },
  { startMs: 45100, endMs: 51533, text: "The Stability Fingerprint repeats the claim under every analysis setting: it holds in 24 of 24." },
  { startMs: 52266, endMs: 58300, text: "Barnard's Star is flagged in all 58 exposures, so HIPPARCHUS refuses to compare it." },
  { startMs: 59033, endMs: 64666, text: "The compatibility graph links only exposures that can be compared fairly." },
  { startMs: 65400, endMs: 71133, text: "Asteroid Kleopatra: 31 real detections in 7 visits match JPL Horizons with 0.15–0.18 arcsecond rms." },
  { startMs: 71866, endMs: 77200, text: "A distant planet would need stacking along trial motions. This is a simulated test: HIPPARCHUS has not found Planet X." },
];
