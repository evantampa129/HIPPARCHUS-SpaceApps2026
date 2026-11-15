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
