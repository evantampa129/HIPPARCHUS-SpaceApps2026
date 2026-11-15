// Writes the English .srt next to the final video from src/captions.ts (the burned-in text).
// Usage: node scripts/make_srt.mjs ../hipparchus_aethenova_29s.en.srt [src/captions_extended.ts]
import fs from "node:fs";

const src = fs.readFileSync(process.argv[3] || new URL("../src/captions.ts", import.meta.url), "utf8");
const cues = [...src.matchAll(/startMs: (\d+), endMs: (\d+), text: "((?:[^"\\]|\\.)*)"/g)].map((m) => ({
  start: +m[1],
  end: +m[2],
  text: JSON.parse(`"${m[3]}"`),
}));
const ts = (ms) => {
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60;
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(h)}:${p(m)}:${p(s)},${p(ms % 1000, 3)}`;
};
const out = cues.map((c, i) => `${i + 1}\n${ts(c.start)} --> ${ts(c.end)}\n${c.text}\n`).join("\n");
fs.writeFileSync(process.argv[2] || "captions.en.srt", out);
console.log(`${cues.length} cues -> ${process.argv[2]}`);
