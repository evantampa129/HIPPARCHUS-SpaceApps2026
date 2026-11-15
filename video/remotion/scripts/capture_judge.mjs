// Screenshots of the real Judge Mode page (docs/index.html, published on GitHub Pages):
// the three result cards and the RW Aur robustness heatmap, in the page's dark theme.
//   PW=/path/to/playwright-core CHROME=/path/to/chrome-headless-shell node scripts/capture_judge.mjs
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright-core");
const page = "file://" + path.resolve("../../docs/index.html");
const out = path.resolve("public/judge");

const b = await chromium.launch({ executablePath: process.env.CHROME });
const pg = await b.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2, colorScheme: "dark" });
await pg.goto(page);
await pg.waitForTimeout(500);
await pg.locator(".cards").first().screenshot({ path: `${out}/cards.png` });
await pg.locator(".rc").first().screenshot({ path: `${out}/card_rwaur.png` });
await pg.locator(".rc").nth(1).screenshot({ path: `${out}/card_barnard.png` });
await pg.locator("table.heat").first().screenshot({ path: `${out}/heatmap.png` });
await pg.locator(".flowd").first().screenshot({ path: `${out}/flow.png` });
await b.close();
