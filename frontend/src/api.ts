// These types mirror the JSON our FastAPI backend returns. We only list the
// fields the page actually reads; the backend sends more (see the evidence file).

export const API = "/api";

export interface Target { id: string; name: string; ra: number; dec: number; detector: string; why: string }

export interface Issue { code: string; severity: "reject" | "warn"; message: string }

export interface Epoch {
  obs_id: string; mjd: number; date_obs: string;
  wavelength_um: number; bandwidth_um: number; usable: boolean; issues: Issue[];
  provenance: { obs: { access_url: string; doi: string; release: string; publisher_did: string };
                cutout: { url: string; sha256: string; cached: boolean } };
}

export interface Phot { flux: number; flux_err: number; sky: number; n_pix: number }

export interface Pair {
  pair_id: number; a: string; b: string; dt_days: number;
  lambda_a_um: number; lambda_b_um: number;
  flux_a: Phot; flux_b: Phot; delta_flux: number; delta_flux_err: number;
  significance: number | null; changed: boolean;
  centroid_shift_arcsec: { dra: number; ddec: number; total: number };
  max_abs_z: number | null;
  flux_ratio: number | null;
  control_star: { x: number; y: number; flux_a: number; flux_b: number; ratio: number; significance: number | null } | null;
}

export interface Analysis {
  analysis_id: string; ra: number; dec: number; detector: string;
  archive_status: "live" | "partial" | "cached"; generated_at: string;
  n_epochs: number; n_usable: number;
  epochs: Epoch[]; failed_downloads: unknown[];
  refused_pairs: Record<string, number>;
  comparisons: Pair[]; null_tests: Pair[];
}

export interface Observations {
  archive_status: string; queried_at?: string; errors: string[];
  sources: { release: string; url: string; sha256: string }[];
  per_detector: Record<string, number>; observations: unknown[];
}

// One helper for every GET: the backend explains failures in "detail", and we
// show that text to the user as is, instead of a generic error.
export async function get<T>(path: string, params: Record<string, string | number>): Promise<T> {
  const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  const r = await fetch(`${API}${path}?${q}`);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

export interface StabilityCell {
  r_ap: number; annulus: [number, number]; mask: string; calibration: string;
  n_pairs: number; complete: boolean; strongest_ratio: number | null; max_abs_sig: number | null;
  claim_holds: Record<string, boolean> | null;
}

export interface Robustness {
  source: string; verdict: string; systematic_floor: number | null;
  settings: { apertures_px: number[]; annuli_px: [number, number][]; rule: string };
  claims: { claim: string; verdict: string; n_checks: number; n_holding: number }[];
  stability: StabilityCell[];
  trials: { n_tests: number; p_any_false_alarm: number; sigma_bonferroni: number } | null;
}

// ---- Explorer endpoints (backend/hipparchus/api_explore.py) ----

export interface HipsLayer {
  id: string; kind: "spherex" | "context"; label: string; url: string; credit: string;
  status: { ok: boolean; http_status: number | null; message: string };
  hips_pixel_arcsec?: number | null;
  properties?: Record<string, string | null>;
}

export interface HipsStatus {
  checked_at: string; layers: HipsLayer[]; spherex_available: boolean;
  channels_um: number[]; channels_source: string; native_pixel_arcsec: number;
  judge_mode_url: string; cached: boolean;
}

export interface ExploreMeta {
  targets: Target[]; cutout_size_deg: number; native_pixel_arcsec: number;
  aperture_radius_px: number; sky_annulus_px: [number, number];
  max_dlambda_fraction: number; judge_mode_url: string;
}

export interface Resolved {
  query: string; oname: string | null; otype: string | null; resolver: string;
  ra: number; dec: number; ra_j2000: number; dec_j2000: number; epoch: number;
  pm_ra_masyr: number | null; pm_dec_masyr: number | null; note: string; cached: boolean;
}

export interface SpecPoint {
  obs_id: string; detector: string; mjd: number; date_obs: string;
  wavelength_um: number; bandwidth_um: number; usable: boolean; measured: boolean; reasons: string[];
  flux: number | null; flux_err: number | null; flux_mjy: number | null; flux_err_mjy: number | null;
  n_pix: number; release: string | null; doi: string | null;
}

export interface Spectrum {
  analysis_id: string; detector: string; ra: number; dec: number; points: SpecPoint[];
  units: { native: string; converted: string };
  aperture_radius_px: number; sky_annulus_px: [number, number]; max_dlambda_fraction: number;
  comparisons: { a: string; b: string }[]; refused_pairs: Record<string, number>; coadded: false;
}

export type Grid = (number | null)[][];

export interface EpochMeta {
  obs_id: string; date_obs: string; mjd: number; detector: string; wavelength_um: number;
  bandwidth_um: number; usable: boolean; release: string | null; doi: string | null; cutout_sha256: string | null;
}

interface PixelGeometry {
  unit: string; shape: [number, number]; masked: number[][];
  x: number; y: number; aperture_radius_px: number; sky_annulus_px: [number, number]; pixel_arcsec: number;
}

export interface EpochPixels extends PixelGeometry { kind: "epoch"; image: Grid; meta: EpochMeta }
export interface PairPixels extends PixelGeometry {
  kind: "pair"; a: Grid; b: Grid; diff: Grid; z: Grid; meta_a: EpochMeta; meta_b: EpochMeta;
  significance: number | null; dt_days: number | null; note: string;
}
