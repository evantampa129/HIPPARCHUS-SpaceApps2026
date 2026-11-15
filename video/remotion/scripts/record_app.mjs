// Records the real HIPPARCHUS app (served on localhost:8080) in headless Chromium,
// same steps as ../record_app.py, and writes the time of every step so the composition
// can cut the waiting out.
//
//   (in backend/)  .venv/bin/uvicorn hipparchus.serve:app --port 8080
//   CHROME=/path/to/chrome-headless-shell node scripts/record_app.mjs
//
// playwright-core is not a dependency of the video project (it is only needed here):
// install it anywhere and point PW to it, e.g. PW=/tmp/pw/node_modules/playwright-core
// Output: public/rec/app.mp4 + public/rec/marks.json (seconds from the start of the recording)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const out = path.resolve("public/rec");
const raw = path.join(out, "raw");
fs.mkdirSync(raw, { recursive: true });

const b = await chromium.launch({ executablePath: process.env.CHROME });
const ctx = await b.newContext({
  viewport: { width: 1280, height: 720 },
  deviceScaleFactor: 1.5, // frames at 1920x1080, so the text stays sharp
});
const pg = await ctx.newPage();
// Playwright's own recorder writes 1 Mbit/s VP8 (blurry text), so the Chrome DevTools
// screencast is used instead: every JPEG frame is kept with its timestamp and turned into
// a constant 30 fps H.264 file afterwards (ffmpeg concat with per-frame durations).
const cdp = await ctx.newCDPSession(pg);
const frames = [];
cdp.on("Page.screencastFrame", async (f) => {
  const name = `f${String(frames.length).padStart(5, "0")}.jpg`;
  fs.writeFileSync(path.join(raw, name), Buffer.from(f.data, "base64"));
  frames.push({ name, ts: f.metadata.timestamp });
  await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
const t0 = Date.now();
const marks = {};
const mark = (k) => { marks[k] = (Date.now() - t0) / 1000; console.log(k, marks[k]); };
const wait = (s) => pg.waitForTimeout(s * 1000);

await pg.goto("http://localhost:8080/");
await pg.waitForSelector(".preset");
await wait(1);
mark("start");
await pg.getByRole("button", { name: "RW Aurigae" }).click();
await wait(0.8);
await pg.getByRole("button", { name: "1. Search archive" }).click();
mark("search_click");
await pg.waitForSelector("text=Archive search", { timeout: 180000 });
mark("search_done");
await wait(2);
await pg.getByRole("button", { name: "2. Analyze epochs" }).click();
mark("analyze_click");
await pg.waitForSelector("text=Valid comparisons", { timeout: 600000 }).catch(() => pg.waitForSelector("text=valid comparisons", { timeout: 600000 }));
mark("analyze_done");
await wait(2);
// smooth scroll down to the timeline
await pg.locator(".timeline").evaluate((e) => e.scrollIntoView({ behavior: "smooth", block: "center" }));
await wait(1.5);
mark("timeline");
await pg.getByRole("button", { name: "Play usable epochs in time order" }).click();
await wait(4);
await pg.getByRole("button", { name: "Pause" }).click();
await pg.locator(".grid4").evaluate((e) => e.scrollIntoView({ behavior: "smooth", block: "center" }));
await wait(1.5);
mark("comparison");
await wait(3);
mark("comparison_end");
await pg.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
await wait(1);
await pg.getByRole("button", { name: "Barnard's Star" }).click();
await wait(0.5);
await pg.getByRole("button", { name: "2. Analyze epochs" }).click();
mark("barnard_click");
await pg.waitForSelector("text=No valid comparison", { timeout: 600000 });
mark("barnard_done");
await pg.locator(".refuse").evaluate((e) => e.scrollIntoView({ behavior: "smooth", block: "center" }));
await wait(3);
mark("refusal");
await wait(2);
mark("end");
await cdp.send("Page.stopScreencast");
await ctx.close();
await b.close();
// Marks are relative to the first frame of the recording.
const first = frames[0].ts;
const shift = first * 1000 - t0; // ms between t0 and the first frame (wall clock)
for (const k of Object.keys(marks)) marks[k] = +(marks[k] - shift / 1000).toFixed(3);
let list = "";
frames.forEach((f, i) => {
  const next = i + 1 < frames.length ? frames[i + 1].ts : f.ts + 0.5;
  list += `file '${f.name}'\nduration ${(next - f.ts).toFixed(4)}\n`;
});
list += `file '${frames[frames.length - 1].name}'\n`;
fs.writeFileSync(path.join(raw, "list.txt"), list);
execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", path.join(raw, "list.txt"),
  "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "14",
  "-movflags", "+faststart", path.join(out, "app.mp4")]);
fs.writeFileSync(path.join(out, "marks.json"), JSON.stringify(marks, null, 2) + "\n");
console.log(frames.length, "frames ->", path.join(out, "app.mp4"));
