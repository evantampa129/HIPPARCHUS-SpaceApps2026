// Colour maps, stretches and PNG export helpers for the pixel viewer.
// We keep them free of React so the export uses exactly the same code as the screen.

export type Rgb = [number, number, number];

// Colour maps as a few anchor colours, linearly interpolated. The anchors are
// sampled from the matplotlib maps of the same name, which is close enough for display.
const ANCHORS: Record<string, Rgb[]> = {
  gray: [[0, 0, 0], [255, 255, 255]],
  cividis: [[0, 34, 78], [37, 60, 108], [87, 92, 109], [124, 123, 120], [166, 157, 117], [210, 193, 98], [253, 234, 69]],
  viridis: [[68, 1, 84], [70, 50, 127], [54, 92, 141], [39, 127, 142], [31, 161, 135], [74, 194, 109], [159, 218, 58], [253, 231, 37]],
  rdbu: [[5, 48, 97], [33, 102, 172], [146, 197, 222], [247, 247, 247], [244, 165, 130], [178, 24, 43], [103, 0, 31]],
  puor: [[45, 0, 75], [84, 39, 136], [178, 171, 210], [247, 247, 247], [253, 184, 99], [224, 130, 20], [127, 59, 8]],
};

export const SEQUENTIAL_MAPS = [
  { id: "gray", label: "grey" },
  { id: "cividis", label: "cividis (colour-blind safe)" },
  { id: "viridis", label: "viridis (colour-blind safe)" },
];
export const DIVERGING_MAPS = [
  { id: "rdbu", label: "blue–white–red (as the PNGs)" },
  { id: "puor", label: "purple–orange (colour-blind safe)" },
];

const LUTS: Record<string, Uint8ClampedArray> = {};
export function lut(name: string): Uint8ClampedArray {
  if (LUTS[name]) return LUTS[name];
  const a = ANCHORS[name] ?? ANCHORS.gray;
  const out = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * (a.length - 1);
    const k = Math.min(Math.floor(t), a.length - 2), f = t - k;
    for (let c = 0; c < 3; c++) out[i * 3 + c] = a[k][c] + (a[k + 1][c] - a[k][c]) * f;
  }
  return (LUTS[name] = out);
}

export type Stretch = "linear" | "sqrt" | "asinh" | "log";
export const STRETCHES: { id: Stretch; label: string }[] = [
  { id: "linear", label: "linear" }, { id: "sqrt", label: "square root" },
  { id: "asinh", label: "asinh (as the PNGs)" }, { id: "log", label: "log" },
];

// t in [0, 1] after clipping to the limits; returns the display level in [0, 1].
export function stretch(t: number, s: Stretch): number {
  t = Math.min(1, Math.max(0, t));
  if (s === "sqrt") return Math.sqrt(t);
  if (s === "asinh") return Math.asinh(20 * t) / Math.asinh(20);
  if (s === "log") return Math.log10(1 + 999 * t) / 3;
  return t;
}

export function percentile(vals: number[], p: number): number {
  if (!vals.length) return NaN;
  const s = [...vals].sort((a, b) => a - b);
  const i = Math.min(s.length - 1, Math.max(0, Math.round((p / 100) * (s.length - 1))));
  return s[i];
}

// ---- PNG metadata: we add tEXt chunks so the exported file carries its own credit line.

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// tEXt is Latin-1 only, so we replace anything else (µ, ″, σ) with plain ASCII.
const latin1 = (s: string) => s.replace(/″/g, "\"").replace(/′/g, "'").replace(/σ/g, "sigma").replace(/[—–−]/g, "-")
  .replace(/→/g, "->").replace(/[^\x20-\x7e\n\xa0-\xff]/g, "?");

export async function addPngText(blob: Blob, entries: Record<string, string>): Promise<Blob> {
  const src = new Uint8Array(await blob.arrayBuffer());
  const chunks: Uint8Array[] = [];
  for (const [k, v] of Object.entries(entries)) {
    const data = new TextEncoder().encode(`${latin1(k)}\0${latin1(v)}`);
    const chunk = new Uint8Array(12 + data.length);
    const dv = new DataView(chunk.buffer);
    dv.setUint32(0, data.length);
    chunk.set([0x74, 0x45, 0x58, 0x74], 4); // "tEXt"
    chunk.set(data, 8);
    dv.setUint32(8 + data.length, crc32(chunk.subarray(4, 8 + data.length)));
    chunks.push(chunk);
  }
  // We insert right after IHDR (8-byte signature + 25-byte IHDR chunk).
  const at = 33;
  const total = src.length + chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  out.set(src.subarray(0, at), 0);
  let o = at;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  out.set(src.subarray(at), o);
  return new Blob([out], { type: "image/png" });
}

export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const CREDIT = "SPHEREx data: NASA/IPAC Infrared Science Archive (IRSA). Processed with HIPPARCHUS, team AETHENOVA, NASA Space Apps 2026. Not an official NASA product.";

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
