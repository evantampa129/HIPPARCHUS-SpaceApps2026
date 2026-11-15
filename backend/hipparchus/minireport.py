"""Mini scientific report per validated case, generated from the evidence JSON.

Every number on the page is read from submission/evidence at build time; the
prose around it holds none. Output is one self-contained HTML file (CSS and
figures inline). If headless Chrome/Chromium is installed we also print it to
PDF; otherwise we say so and keep the HTML.

    python -m hipparchus.minireport            # all cases -> submission/bundles/reports/
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from hipparchus.bundle import CASES, EVIDENCE, ROOT

REPORT_DIR = ROOT / "submission" / "bundles" / "reports"
BANNER = "Built from the published evidence (cached, not recomputed)."


def _load(name: str, evidence_dir: Path) -> dict | None:
    p = evidence_dir / name
    return json.loads(p.read_text()) if p.exists() else None


def _f(x, nd=2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        if x != 0 and (abs(x) < 10 ** -nd or abs(x) >= 1e5):
            return f"{x:.{nd}e}"
        return f"{x:.{nd}f}"
    return html.escape(str(x))


def _e(s) -> str:
    return html.escape(str(s))


def _table(head: list[str], rows: list[list]) -> str:
    h = "".join(f"<th>{_e(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c if isinstance(c, str) else _f(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def _link(url: str, text: str | None = None) -> str:
    return f'<a href="{_e(url)}">{_e(text or url)}</a>'


# ---------------------------------------------------------------- figures

def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf.getvalue()


def figures(case: str, evidence_dir: Path = EVIDENCE) -> dict[str, bytes]:
    """Small PNGs drawn straight from the evidence."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    spec = CASES[case]
    ev = _load(spec["evidence"], evidence_dir)
    out = {}
    if spec["kind"] == "change":
        # where each epoch sits in wavelength and time, and whether it was usable
        fig, ax = plt.subplots(figsize=(6.4, 3.2))
        for usable, colour, label in ((True, "#1f6f43", "usable"), (False, "#b03a2e", "rejected")):
            pts = [(e["mjd"], e["wavelength_um"]) for e in ev["epochs"] if e["usable"] == usable]
            if pts:
                ax.scatter(*zip(*pts), s=14, c=colour, label=f"{label} ({len(pts)})")
        ax.set_xlabel("MJD")
        ax.set_ylabel("wavelength at target (um)")
        ax.legend(fontsize=8)
        ax.set_title(f"{ev['target']['name']}: epochs ({ev['detector']})", fontsize=10)
        out["epochs"] = _png(fig)
        comps = ev["comparisons"]
        if comps:
            fig, ax = plt.subplots(figsize=(6.4, 3.2))
            x = list(range(len(comps)))
            ax.errorbar(x, [c["delta_flux"] for c in comps], yerr=[c["delta_flux_err"] for c in comps],
                        fmt="o", ms=4, c="#1f4e79", label="target: flux_b - flux_a")
            ctrl = [(i, c["control_star"]["flux_b"] - c["control_star"]["flux_a"]) for i, c in enumerate(comps)
                    if c.get("control_star")]
            if ctrl:
                ax.scatter(*zip(*ctrl), marker="x", c="#888", label="control star")
            ax.axhline(0, c="k", lw=0.6)
            ax.set_xticks(x, [f"{c['a'][:7]}\n{c['b'][:7]}" for c in comps], fontsize=6)
            ax.set_ylabel("flux difference (image units)")
            ax.legend(fontsize=8)
            ax.set_title("valid pairs (same wavelength, different visits)", fontsize=10)
            out["pairs"] = _png(fig)
    else:
        import math
        rows = []
        for e in ev["exposures"]:
            m, h = e.get("measured"), e.get("horizons_spherex")
            if m and h and m.get("ra") is not None:
                c = math.cos(math.radians(h["dec"]))
                rows.append((e["mjd_mid"], (m["ra"] - h["ra"]) * c * 3600, (m["dec"] - h["dec"]) * 3600))
        if rows:
            t0 = min(r[0] for r in rows)
            fig, ax = plt.subplots(figsize=(6.4, 3.2))
            ax.scatter([(r[0] - t0) * 24 for r in rows], [r[1] for r in rows], s=12, label="RA cos Dec")
            ax.scatter([(r[0] - t0) * 24 for r in rows], [r[2] for r in rows], s=12, marker="s", label="Dec")
            ax.axhline(0, c="k", lw=0.6)
            ax.set_xlabel("hours since first detection")
            ax.set_ylabel("measured - Horizons@SPHEREx (arcsec)")
            ax.legend(fontsize=8)
            ax.set_title(f"{ev['object']}: astrometric residuals", fontsize=10)
            out["residuals"] = _png(fig)
    return out


# ---------------------------------------------------------------- sections

def _change_sections(case: str, evidence_dir: Path) -> list[tuple[str, str]]:
    spec = CASES[case]
    ev = _load(spec["evidence"], evidence_dir)
    cfg = ev["config"]
    val = _load("validation.json", evidence_dir) or {}
    vt = next((t for t in val.get("targets", []) if t["id"] == spec["target_id"]), None)
    rob = (_load("robustness.json", evidence_dir) or {}).get("targets", {}).get(spec["target_id"])
    comps = ev["comparisons"]
    changed = [c for c in comps if c["changed"]]
    dates = sorted(e["date_obs"] for e in ev["epochs"])
    dois = Counter((e["provenance"]["obs"]["release"], e["provenance"]["obs"]["doi"]) for e in ev["epochs"])
    t = ev["target"]
    s = []

    s.append(("Question", f"<p>{_e(t['why'])}</p><p>Did <b>{_e(t['name'])}</b> (RA {_f(t['ra'], 4)}, Dec "
              f"{_f(t['dec'], 4)}) change brightness between SPHEREx visits, comparing only exposures that "
              f"saw it at the same wavelength on detector {_e(ev['detector'])}?</p>"))

    s.append(("Data", f"<p>{_f(ev['n_epochs'])} exposures between {_e(dates[0][:10] if dates else 'n/a')} and "
              f"{_e(dates[-1][:10] if dates else 'n/a')}; archive answer: <code>{_e(ev['archive_status'])}</code>; "
              f"failed downloads: {_f(len(ev['failed_downloads']))}.</p>"
              + _table(["release", "DOI", "exposures"], [[_e(r), _link('https://doi.org/' + d, d), n] for (r, d), n in sorted(dois.items())])
              + _table(["archive query", "sha256 of the raw answer"],
                       [[_link(q["url"], q["release"]), f"<code>{_e(q['sha256'])}</code>"] for q in ev["archive_queries"]])))

    issues = Counter(i["code"] for e in ev["epochs"] for i in e["issues"] if i["severity"] == "reject")
    s.append(("Filtering and refusals",
              f"<p>{_f(ev['n_usable'])} of {_f(ev['n_epochs'])} exposures are usable. A pair is compared only "
              f"when the wavelength shift is at most {_f(cfg['max_wavelength_shift_fraction_of_bandwidth'])} of a "
              f"channel width and no pixel in the {_f(cfg['aperture_radius_px'], 1)}-px aperture carries a bad flag.</p>"
              + _table(["exposure rejected because", "exposures"], [[_e(k), v] for k, v in issues.most_common()])
              + _table(["pair refused because", "pairs"], [[_e(k), v] for k, v in sorted(ev["refused_pairs"].items(), key=lambda kv: -kv[1])])
              + f"<p>Bad flag planes: <code>{_e(', '.join(cfg['bad_flag_planes']))}</code>.</p>"))

    rows = [[_e(c["a"]), _e(c["b"]), c["dt_days"], c["lambda_a_um"], f"{_f(c['flux_a']['flux'])} ± {_f(c['flux_a']['flux_err'])}",
             f"{_f(c['flux_b']['flux'])} ± {_f(c['flux_b']['flux_err'])}", c["flux_ratio"], c["significance"],
             "<b>change</b>" if c["changed"] else "no"] for c in comps]
    verdict = (f"{len(changed)} of {len(comps)} valid pairs differ by at least {_f(cfg['detection_sigma'], 1)} sigma."
               if comps else "No pair passed the checks, so the tool makes no brightness claim for this target.")
    s.append(("Measurement", f"<p><b>{_e(verdict)}</b> Aperture photometry, radius {_f(cfg['aperture_radius_px'], 1)} px, "
              f"sky annulus {_f(cfg['sky_annulus_px'][0], 1)}-{_f(cfg['sky_annulus_px'][1], 1)} px, after reprojecting one "
              f"epoch onto the other.</p>"
              + (_table(["epoch a", "epoch b", "dt (d)", "lambda (um)", "flux a", "flux b", "ratio b/a", "sigma", "verdict"], rows) if rows else "")))

    u = ["<p>Each pair's error combines both epochs' pipeline variances, propagated through the aperture "
         "and the reprojection.</p>"]
    nt = (vt or {}).get("null_test", {})
    if vt and not nt.get("n"):
        u.append(f"<p>Null test: no usable same-visit pair (n = {_f(nt.get('n', 0))}), so no noise check is possible here.</p>")
    if nt.get("n"):
        u.append(f"<p>Null test (same-visit pairs, where nothing can have changed): n = {_f(nt['n'])}, mean "
                 f"{_f(nt['mean'])} sigma, std {_f(nt['std'])}, robust std {_f(nt['robust_std'])}, fraction beyond "
                 f"5 sigma {_f(nt['frac_abs_over_5'])}.</p>")
        inj = vt.get("injection_SIMULATED", [])
        if inj:
            u.append("<p><b>SIMULATED</b> injections into the real cutouts (recovered fraction by injected S/N):</p>"
                     + _table(["injected S/N", "n", "recovered"], [[i["snr_injected"], i["n"], i["recovered_fraction"]] for i in inj]))
    if rob:
        tr = rob.get("trials")
        if tr:
            u.append(f"<p>Look-elsewhere: {_f(tr['n_tests'])} tests; chance of any false alarm at the threshold "
                     f"{_f(tr['p_any_false_alarm'], 3)}; Bonferroni-equivalent threshold {_f(tr['sigma_bonferroni'])} sigma.</p>")
    s.append(("Uncertainty", "".join(u)))

    ctrl = [[_e(c["a"]), _e(c["b"]), c["control_star"]["ratio"], c["control_star"]["significance"],
             c["centroid_shift_arcsec"]["total"]] for c in comps if c.get("control_star")]
    cx = []
    if ctrl:
        cx.append("<p>A field star measured the same way in every pair must not change:</p>"
                  + _table(["epoch a", "epoch b", "control ratio", "control sigma", "target centroid shift (arcsec)"], ctrl))
    if rob and rob.get("verdict"):
        cx.append(f"<p>Robustness over the aperture/annulus/mask/calibration grid: <code>{_e(json.dumps(rob['verdict']))[:600]}</code></p>")
    if not cx:
        cx.append("<p>No valid pair, so there is no pair-level control; the refusal itself is the result.</p>")
    s.append(("Controls", "".join(cx)))

    s.append(("Limitations", "<ul><li>Fixed circular aperture, not PSF fitting; a change in PSF width between "
              "visits leaks into the ratio for small apertures (see the robustness grid).</li>"
              "<li>Only pairs at matching wavelength are compared, so most possible pairs are refused by design.</li>"
              "<li>Fluxes are in pipeline image units; the ratio is the claim, not an absolute calibration.</li>"
              "<li>Coordinates centre the cutout only; a fast-moving star is followed by re-centroiding.</li></ul>"))

    cut = [e["provenance"]["cutout"]["url"] for e in ev["epochs"] if e["provenance"].get("cutout")]
    s.append(("Links", "<ul>" + "".join(f"<li>{_link('https://doi.org/' + d, d)} ({_e(r)})</li>" for r, d in sorted(dois))
              + f"<li>Reproduction bundle: <code>/reproduce/{_e(case)}.zip</code></li></ul>"
              + f"<details><summary>{len(cut)} cutout URLs</summary><ul>"
              + "".join(f"<li>{_link(u)}</li>" for u in cut) + "</ul></details>"))
    return s


def _motion_sections(evidence_dir: Path) -> list[tuple[str, str]]:
    ev = _load(CASES["kleopatra"]["evidence"], evidence_dir)
    st, fm = ev["settings"], ev["fitted_motion"]
    res = ev["residuals_vs_horizons_spherex_arcsec"]["linked_track_members"]
    geo = ev["residuals_vs_horizons_geocentric_arcsec"]["all_detections_near_prediction"]
    dois = Counter(e["doi"] for e in ev["exposures"])
    s = []
    s.append(("Question", f"<p>{_e(ev['experiment'])}.</p><p>Claim: {_e(ev['claim'])}.</p>"))
    s.append(("Data", f"<p>{_e(ev['object'])}; {_f(ev['archive']['n_exposures_in_window'])} SPHEREx exposures in MJD "
              f"{_f(ev['field']['window_mjd'][0], 2)}-{_f(ev['field']['window_mjd'][1], 2)}, cutouts of "
              f"{_f(ev['field']['cutout_size_deg'], 3)} deg. Ephemeris: JPL Horizons at SPHEREx "
              f"(<code>{_e(ev['horizons']['observer_spherex'])}</code>).</p>"
              + _table(["DOI", "exposures"], [[_link('https://doi.org/' + d, d), n] for d, n in sorted(dois.items())])
              + _table(["archive query", "sha256"], [[_link(q["url"], q["release"]), f"<code>{_e(q['sha256'])}</code>"] for q in ev["archive"]["queries"]])))
    pf = ev["pipeline_flag_finding"]
    s.append(("Filtering and refusals", f"<p>Blind search first: {_f(ev['blind_search']['n_detections'])} detections at "
              f"{_f(st['nsigma'], 1)} sigma, {_f(ev['blind_search']['n_static'])} removed as static (within "
              f"{_f(st['static_radius_arcsec'], 1)} arcsec over at least {_f(st['min_dt_static_hours'], 1)} h); links need "
              f"{_f(st['min_visits'])} visits and rates {_f(st['v_min_arcsec_h'], 1)}-{_f(st['v_max_arcsec_h'], 1)} arcsec/h.</p>"
              f"<p>{_e(pf['what'])}: {_f(pf['n_with_outlier'])} of {_f(pf['n_exposures'])}. {_e(pf['consequence'])}.</p>"))
    tr = ev["blind_search"]["tracks"]
    s.append(("Measurement", _table(["track", "detections", "visits", "rate RA cosDec (\"/h)", "rate Dec (\"/h)", "fit rms (\")", "median offset from Horizons (\")", "matches Horizons"],
                                    [[t["track"], t["n_detections"], t["n_visits"], t["rate_ra_cosdec_arcsec_h"], t["rate_dec_arcsec_h"], t["fit_rms_arcsec"], t["median_offset_from_horizons_arcsec"], t["matches_horizons"]] for t in tr])
              + f"<p>Fitted rate {_f(fm['measured_rate_arcsec_h']['ra_cosdec'], 4)}, {_f(fm['measured_rate_arcsec_h']['dec'], 4)} arcsec/h; "
              f"Horizons with the same model {_f(fm['horizons_same_model_rate_arcsec_h']['ra_cosdec'], 4)}, "
              f"{_f(fm['horizons_same_model_rate_arcsec_h']['dec'], 4)} arcsec/h.</p>"))
    fl = ev["astrometric_floor_field_stars"]
    s.append(("Uncertainty", f"<p>Rate difference {_f(fm['rate_difference_arcsec_h']['sigma_ra_cosdec'])} sigma (RA) and "
              f"{_f(fm['rate_difference_arcsec_h']['sigma_dec'])} sigma (Dec); rate errors "
              f"{_f(fm['measured_rate_arcsec_h']['err_ra_cosdec'], 4)} arcsec/h. Residuals of the {_f(res['n'])} linked detections: "
              f"rms {_f(res['rms_ra_cosdec'])}\" (RA cos Dec), {_f(res['rms_dec'])}\" (Dec), median total {_f(res['median_total'])}\". "
              f"Field-star floor (S/N >= 20): {_f(fl['floor_arcsec_bright_snr_ge_20'])}\" from {_f(fl['n_stars'])} stars.</p>"))
    inj = ev["simulated_injection_recovery"]
    fp = ev["simulated_false_positive_tests"]
    s.append(("Controls", f"<p>Parallax control: against a <i>geocentric</i> ephemeris the median residual grows to "
              f"{_f(geo['median_total'])}\", as expected for an observer in low Earth orbit.</p>"
              f"<p>Tracks not matching Kleopatra: {_f(ev['blind_search']['n_tracks_not_matching_kleopatra'])} (vetted in the follow-up evidence).</p>"
              "<p><b>SIMULATED</b> movers injected into the real cutouts:</p>"
              + _table(["S/N", "speed (\"/h)", "trials in frame", "recovered", "rate"], [[i["snr"], i["speed_arcsec_h"], i["trials_with_ge_3_visits_in_frame"], i["recovered"], i["recovery_rate"]] for i in inj])
              + f"<p><b>{_e(fp['label'])}</b> time-shuffled real data: {_f(fp['time_shuffled_real_data']['runs_with_any_track'])} of "
              f"{_f(fp['time_shuffled_real_data']['runs'])} runs give a 3-visit link, {_f(fp['time_shuffled_real_data']['runs_with_track_ge_5_visits'])} a 5-visit one.</p>"))
    s.append(("Limitations", "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in ev["limitations"]) + "</ul>"))
    s.append(("Links", "<ul>" + "".join(f"<li>{_link('https://doi.org/' + d, d)}</li>" for d in sorted(dois))
              + f"<li>{_link(ev['horizons']['api'], 'JPL Horizons API')}</li><li>Reproduction bundle: <code>/reproduce/kleopatra.zip</code></li></ul>"
              + f"<details><summary>{len(ev['exposures'])} cutout URLs</summary><ul>"
              + "".join(f"<li>{_link(e['cutout_url'])}</li>" for e in ev["exposures"]) + "</ul></details>"))
    return s


CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:0 auto;padding:1rem;color:#1b1b1b;background:#fff}
h1{font-size:1.4rem}h2{font-size:1.1rem;border-bottom:1px solid #ccc;margin-top:1.6rem}
.banner{background:#eef4fb;border:1px solid #b6cde6;padding:.5rem .8rem;border-radius:4px}
table{border-collapse:collapse;margin:.5rem 0;font-size:.85rem;display:block;overflow-x:auto}
td,th{border:1px solid #ddd;padding:.2rem .45rem;text-align:left;white-space:nowrap}th{background:#f4f4f4}
code{font-size:.8rem;word-break:break-all}img{max-width:100%}footer{margin-top:2rem;font-size:.8rem;color:#555}
@media print{details{display:none}table{display:table;font-size:.68rem}td,th{white-space:normal}}"""


def render_html(case: str, evidence_dir: Path = EVIDENCE) -> str:
    spec = CASES[case]
    secs = _motion_sections(evidence_dir) if spec["kind"] == "motion" else _change_sections(case, evidence_dir)
    figs = figures(case, evidence_dir)
    imgs = "".join(f'<figure><img alt="{_e(n)}" src="data:image/png;base64,{base64.b64encode(b).decode()}"></figure>'
                   for n, b in figs.items())
    body = "".join(f"<h2>{_e(t)}</h2>{c}" + (imgs if t == "Measurement" else "") for t, c in secs)
    src = evidence_dir / spec["evidence"]
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    gen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            f"content=\"width=device-width,initial-scale=1\"><title>{_e(spec['title'])}</title><style>{CSS}</style></head>"
            f"<body><h1>{_e(spec['title'])}</h1><p class=\"banner\">{_e(BANNER)} Source: "
            f"<code>submission/evidence/{_e(spec['evidence'])}</code>, sha256 <code>{sha}</code>.</p>{body}"
            f"<footer>HIPPARCHUS mini report, generated {gen} from the evidence file above.</footer></body></html>")


def pdf_tool() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Print with headless Chrome if present. Returns False when no tool is installed."""
    tool = pdf_tool()
    if not tool:
        return False
    subprocess.run([tool, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
                   capture_output=True, timeout=120, check=False)
    return pdf_path.exists() and pdf_path.stat().st_size > 0


def export(cases=None, out_dir: Path = REPORT_DIR, evidence_dir: Path = EVIDENCE, pdf: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    done = {}
    for c in cases or CASES:
        h = out_dir / f"{c}.html"
        h.write_text(render_html(c, evidence_dir))
        done[c] = {"html": str(h), "pdf": None}
        if pdf:
            p = out_dir / f"{c}.pdf"
            if to_pdf(h, p):
                done[c]["pdf"] = str(p)
    return done


if __name__ == "__main__":
    r = export()
    for c, v in r.items():
        print(c, v["html"], v["pdf"] or "(no PDF: no headless Chrome/Chromium found)")
