"""Build the static Judge Mode page (docs/) and one evidence capsule per target.

Everything comes from what is already saved: the cached real SPHEREx cutouts,
the archive listings in data/manifests and the files in submission/evidence.
No new analysis choices are made and no live archive query is sent, so the page
loads instantly and shows exactly the published numbers.

    python scripts/make_judge_site.py      # writes docs/index.html, docs/img/, docs/capsule_*.json
"""

import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from hipparchus import api, archive  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "submission" / "evidence"
OUT = ROOT / "docs"
REPO = "https://github.com/evantampa129/HIPPARCHUS-SpaceApps2026"


def cached_query(ra, dec, **_):
    # Same rule as reproduce_robustness.py: the saved complete listing, never a live call.
    m = json.loads(archive._manifest_path(ra, dec).read_text())
    m["archive_status"] = "cached"
    return m


archive.query = cached_query

LIMITS = {
    "rw_aur": ["The 175σ value is the formal statistical significance. With the 12.5% calibration floor measured from "
               "field stars it is at most 12.4σ; the size of the change (×2.5) is the robust result.",
               "SPHEREx pixels are 6.15″, so the aperture holds both stars of the RW Aur binary (1.6″ apart) and a "
               "faint G = 18.8 star: this is the combined light of the system.",
               "The field-star calibration uses only 0–2 reference stars per cutout, so the 12.5% floor is itself uncertain.",
               "“Brighter in every pair” is sensitive: it fails with a 1.5 px aperture. “At least ×1.5 at ≥5σ” holds in every check.",
               "RW Aur is a known variable young star: a measurement, not a discovery."],
    "barnard": ["Refused because every epoch is saturated or flagged at the star in detector 6; this is a property of "
                "the data, not of our settings.",
                "Barnard's Star moves 10″ per year (1.7 px), so the preset position is propagated; the catalogue match "
                "puts it 0.88 px from SIMBAD."],
    "wise0855": ["Faint target (median S/N ≈ 2.7 per epoch): “no change” means no change above about 5σ of these "
                 "errors, not that the object is constant.",
                 "No field star passes the reference-star criteria in these cutouts, so no calibration floor could be measured.",
                 "Only 4 settings keep every pair measurable; the claim holds in all 4 and in every leave-one-out and "
                 "wavelength-rule check.",
                 "A G = 16.3 field star lies 6.8″ away, inside the aperture."],
}

SUMMARY = {
    "rw_aur": ("Measured variability", "ok",
               "RW Aur is 2.56× brighter one year later at the same wavelength (0.763/0.770 µm). All 8 valid pairs "
               "point the same way; the control star stays within 0.86–1.07."),
    "barnard": ("Comparison refused", "warn",
                "All 58 epochs are saturated or flagged at the star. HIPPARCHUS refuses to compare instead of "
                "reporting a fake change."),
    "wise0855": ("No significant change", "neutral",
                 "27 valid pairs, none changes by 5σ or more (largest |σ| = 1.9). The significances scatter like noise."),
}


def esc(x) -> str:
    return html.escape(str(x))


def capsule(d: dict, rob: dict, cat: dict, graph: dict) -> dict:
    """Machine-readable summary made only from the saved evidence."""
    t = d["target"]
    used = {c["a"] for c in d["comparisons"]} | {c["b"] for c in d["comparisons"]}
    eps = [e for e in d["epochs"] if e["obs_id"] in used] or d["epochs"]
    return {
        "target": t, "coordinates_deg": {"ra": d["ra"], "dec": d["dec"]}, "detector": d["detector"],
        "archive_queries": d["archive_queries"],
        "datasets": ["doi:10.26131/IRSA678 (SPHEREx DR1)", "doi:10.26131/IRSA662 (SPHEREx QR3)"],
        "epochs_found": d["n_epochs"], "epochs_usable": d["n_usable"],
        "observations": [{"obs_id": e["obs_id"], "date": e["date_obs"], "wavelength_um": e["wavelength_um"],
                          "usable": e["usable"], "issues": e["issues"],
                          "image_url": e["provenance"]["obs"]["access_url"],
                          "cutout_url": e["provenance"]["cutout"]["url"],
                          "cutout_sha256": e["provenance"]["cutout"]["sha256"]} for e in eps],
        "method": d["config"],
        "compatibility": {"valid_pairs": len(d["comparisons"]), "refused_pairs_by_reason": d["refused_pairs"]},
        "measurements": [{k: c[k] for k in ("a", "b", "dt_days", "lambda_a_um", "lambda_b_um", "flux_ratio",
                                            "delta_flux", "delta_flux_err", "significance", "control_star")}
                         for c in d["comparisons"]],
        "robustness": {k: rob.get(k) for k in ("verdict", "claims", "systematic_floor", "trials")},
        "catalogue_match": cat,
        "evidence_graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
                           "file": f"submission/evidence/graph_{t['id']}_{d['detector'].lower()}.json"},
        "limitations": LIMITS[t["id"]],
        "reproduce": ["cd backend && python scripts/reproduce_evidence.py",
                      "python scripts/reproduce_robustness.py",
                      "python scripts/make_judge_site.py"],
        "note": "Generated from the saved evidence files; no new measurement was made for this summary.",
    }


def heatmap(rob: dict, settings: dict) -> str:
    claims = rob.get("claims", [])
    if not claims:
        return "<p class='muted'>No stability grid: there is no valid pair to vary the settings on.</p>"
    first = claims[0]["claim"]
    cells = [c for c in rob["stability"] if c["mask"] == "as_flagged" and c["calibration"] == "none"]
    rows = []
    for r in settings["apertures_px"]:
        tds = []
        for an in settings["annuli_px"]:
            c = next((c for c in cells if c["r_ap"] == r and c["annulus"] == list(an)), None)
            ok = c and c["claim_holds"] and c["claim_holds"].get(first)
            cls = "na" if not c or c["claim_holds"] is None else ("ok" if ok else "no")
            txt = f"×{c['strongest_ratio']:.2f}<br><small>{c['max_abs_sig']:.1f}σ</small>" if c else "–"
            tds.append(f"<td class='{cls}'>{txt}</td>")
        rows.append(f"<tr><th>{r}{' (used)' if r == 2 else ''}</th>{''.join(tds)}</tr>")
    head = "".join(f"<th>{a[0]}–{a[1]}</th>" for a in settings["annuli_px"])
    lis = "".join(f"<li><b class='lab {esc(c['verdict'])}'>{esc(c['verdict'])}</b> {esc(c['claim'])} "
                  f"<span class='muted'>({c['n_holding']}/{c['n_checks']} checks)</span></li>" for c in claims)
    return (f"<ul class='claims'>{lis}</ul><table class='heat'><tr><th>aperture px \\ sky annulus px</th>{head}</tr>"
            f"{''.join(rows)}</table><p class='muted'>Cells test “{esc(first)}”: green holds, red fails, grey = "
            f"some pair not measurable. Value: strongest ratio and largest |σ|. Labels follow a fixed rule "
            f"(robust = all checks, sensitive = at least half); they are not probabilities.</p>")


def pair_table(d: dict, rob: dict) -> str:
    sys_sig = {(p["a"], p["b"]): p.get("sig_with_systematics") for p in rob.get("pairs", [])}
    date = {e["obs_id"]: e["date_obs"][:10] for e in d["epochs"]}
    rows = []
    for c in sorted(d["comparisons"], key=lambda c: -abs(c["significance"])):
        s2 = sys_sig.get((c["a"], c["b"]))
        cs = c["control_star"]["ratio"] if c["control_star"] else None
        rows.append(f"<tr><td>{date[c['a']]} → {date[c['b']]}</td><td>{c['lambda_a_um']:.3f}/{c['lambda_b_um']:.3f}</td>"
                    f"<td>×{c['flux_ratio']:.2f}</td><td>{c['significance']:+.1f}</td>"
                    f"<td>{'' if s2 is None else f'{s2:+.1f}'}</td><td>{'' if cs is None else f'×{cs:.2f}'}</td></tr>")
    return ("<div class='scroll'><table class='pairs'><tr><th>dates (a → b)</th><th>λ µm</th><th>flux ratio</th>"
            "<th>σ formal</th><th>σ with calibration floor*</th><th>control star</th></tr>" + "".join(rows) + "</table></div><p class='muted'>* Formal error plus the field-star calibration floor; blank where no "
            "floor could be measured (fewer than 3 pairs with reference stars). Blank control star: none passed the "
            "criteria in that pair.</p>")


def main():
    if (OUT / "img").exists():
        shutil.rmtree(OUT / "img")
    (OUT / "img").mkdir(parents=True)
    rob_all = json.loads((EVID / "robustness.json").read_text())
    cat_all = json.loads((EVID / "catalog_match.json").read_text())
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    client = TestClient(api.app)
    sections = []
    for t in api.TARGETS:
        tid, det = t["id"], t["detector"]
        d = json.loads((EVID / f"{tid}_{det.lower()}.json").read_text())
        graph = json.loads((EVID / f"graph_{tid}_{det.lower()}.json").read_text())
        rob = rob_all["targets"][tid]
        cat = cat_all["targets"].get(tid, {})
        cap = capsule(d, rob, cat, graph)
        (OUT / f"capsule_{tid}.json").write_text(json.dumps(cap, indent=1) + "\n")

        r = client.get("/analyze", params={"ra": t["ra"], "dec": t["dec"], "detector": det}).json()
        aid = r["analysis_id"]
        imgs = ""
        if r["comparisons"]:
            # The pair with the largest |significance|: the strongest evidence for or against a change.
            c = max(r["comparisons"], key=lambda c: abs(c["significance"]))
            figs = []
            for kind, cap_txt in (("a", "earlier"), ("b", "later"), ("diff", "difference"), ("z", "significance map")):
                png = client.get(f"/analysis/{aid}/pair/{c['pair_id']}/{kind}.png").content
                (OUT / "img" / f"{tid}_{kind}.png").write_bytes(png)
                figs.append(f"<figure><img src='img/{tid}_{kind}.png' alt='{cap_txt}'><figcaption>{cap_txt}</figcaption></figure>")
            imgs = (f"<div class='imgs'>{''.join(figs)}</div><p class='muted'>Pair shown: {c['a']} → {c['b']} "
                    f"(the largest |σ|). Real SPHEREx cutouts, later epoch reprojected onto the earlier one; "
                    f"crosshair = target.</p>")
        else:
            usable = [e for e in r["epochs"]]
            e = usable[len(usable) // 2]
            png = client.get(f"/analysis/{aid}/epoch/{e['obs_id']}.png").content
            (OUT / "img" / f"{tid}_epoch.png").write_bytes(png)
            iss = "; ".join(i["message"] for i in e["issues"]) or "none"
            imgs = (f"<div class='imgs'><figure><img src='img/{tid}_epoch.png' alt='epoch'><figcaption>{esc(e['obs_id'])}"
                    f"</figcaption></figure></div><p class='muted'>One real epoch (flagged pixels marked). Reasons "
                    f"recorded for this epoch: {esc(iss.rstrip('.'))}.</p>")

        dates = sorted(e["date_obs"][:10] for e in d["epochs"])
        head, cls, text = SUMMARY[tid]
        refused = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in d["refused_pairs"].items())
        q = "".join(f"<li><a href='{esc(x['url'])}'>{esc(x['release'])} archive query</a> "
                    f"<code>sha256 {esc(x['sha256'][:16])}…</code></li>" for x in d["archive_queries"])
        unc = ""
        if d["comparisons"]:
            tr = rob.get("trials") or {}
            fl = rob.get("systematic_floor")
            unc = (f"<p>Each σ is the formal error from the SPHEREx variance planes, propagated through sky subtraction "
                   f"and reprojection (checked: blank-sky null test spread 0.91, ideal 1). "
                   f"{'A calibration floor of ' + format(100 * fl, '.1f') + '% from field stars is shown separately. ' if fl else ''}"
                   f"With {tr.get('n_tests')} pairs tested, the chance of any false 5σ event is "
                   f"{tr.get('p_any_false_alarm', 0):.1e}.</p>")
        sections.append(f"""
<section class='case' id='{tid}'>
 <h2>{esc(t['name'])} <span class='tag {cls}'>{esc(head)}</span></h2>
 <p class='lead'>{esc(text)}</p>
 <div class='grid'>
  <div><h3>Observed</h3><p>RA {d['ra']}°, Dec {d['dec']}°, {esc(det)}<br>{d['n_epochs']} epochs found, {d['n_usable']} usable<br>
   {dates[0]} → {dates[-1]}</p></div>
  <div><h3>Verified</h3><p>{len(d['comparisons'])} valid pairs (same detector, |Δλ| ≤ half a channel, clean pixels).<br>
   Refused: {esc(refused)}.</p></div>
 </div>
 <h3>Comparison</h3>{imgs}
 {pair_table(d, rob) if d['comparisons'] else ''}
 <h3>Uncertainty</h3>{unc or "<p>No measurement, so no uncertainty: the comparison is refused.</p>"}
 <h3>Challenged: stability fingerprint</h3>{heatmap(rob, rob_all['settings'])}
 <h3>Limitations</h3><ul>{''.join(f'<li>{esc(x)}</li>' for x in LIMITS[tid])}</ul>
 <h3>Provenance</h3><ul>{q}<li>Datasets: SPHEREx DR1 <a href='https://doi.org/10.26131/IRSA678'>doi:10.26131/IRSA678</a>,
   QR3 <a href='https://doi.org/10.26131/IRSA662'>doi:10.26131/IRSA662</a> (NASA/IPAC IRSA)</li>
   <li>Every cutout URL and SHA-256: <a href='capsule_{tid}.json'>evidence capsule (JSON)</a> ·
   <a href='{REPO}/blob/main/submission/evidence/{tid}_{det.lower()}.json'>full evidence file</a></li></ul>
</section>""")

    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>HIPPARCHUS Judge Mode</title>
<style>
:root{{--bg:#0d1220;--card:#151c2e;--fg:#e6e9f0;--muted:#9aa3b5;--line:#2a3550;--ok:#1f6b40;--no:#7a2633;--na:#3a3f4b;--acc:#7cc4ff;--warn:#8a6d1a}}
@media (prefers-color-scheme: light){{:root{{--bg:#f6f7fb;--card:#fff;--fg:#141824;--muted:#5a6375;--line:#d5dae5;--ok:#bfe5cc;--no:#f2c4cb;--na:#e3e5ea;--acc:#0b5cad;--warn:#f3e0a6}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:16px}}
a{{color:var(--acc)}} code{{font-size:13px}} .muted{{color:var(--muted);font-size:14px}}
header h1{{margin:8px 0 4px}} .flow{{font-weight:600;letter-spacing:.04em;color:var(--acc)}}
nav a{{margin-right:14px}}
.case{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:20px 0}}
.tag{{font-size:13px;padding:2px 8px;border-radius:12px;vertical-align:middle}} .tag.ok{{background:var(--ok)}} .tag.warn{{background:var(--warn)}} .tag.neutral{{background:var(--na)}}
.lead{{font-size:17px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media (max-width:640px){{.grid{{grid-template-columns:1fr}}}}
h3{{margin:18px 0 6px;font-size:15px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.imgs{{display:flex;gap:8px;flex-wrap:wrap}} figure{{margin:0;flex:1 1 140px;max-width:220px}} figure img{{width:100%;image-rendering:pixelated;border:1px solid var(--line)}}
figcaption{{font-size:13px;color:var(--muted);text-align:center}}
.scroll{{overflow-x:auto;max-height:320px;overflow-y:auto}}
table{{border-collapse:collapse;font-size:14px;margin:6px 0}} th,td{{border:1px solid var(--line);padding:4px 8px;text-align:center}}
.heat td.ok{{background:var(--ok)}} .heat td.no{{background:var(--no)}} .heat td.na{{background:var(--na)}}
.lab{{text-transform:uppercase;font-size:12px;padding:1px 6px;border-radius:8px;background:var(--na)}} .lab.robust{{background:var(--ok)}} .lab.sensitive{{background:var(--warn)}}
footer{{color:var(--muted);font-size:13px;margin:24px 0}}
</style></head><body><main>
<header><h1>HIPPARCHUS · Judge Mode</h1>
<p class='flow'>OBSERVE → VERIFY → CHALLENGE → EXPLAIN</p>
<p>HIPPARCHUS does not just show the difference between two SPHEREx images. It checks whether the difference can be
interpreted (same detector, same wavelength, clean pixels), challenges the result with other reasonable analysis
choices, and keeps the evidence back to the NASA archive. Three real cases, precomputed from cached SPHEREx cutouts,
so nothing here waits for a live archive download.</p>
<nav><a href='#rw_aur'>RW Aurigae</a><a href='#barnard'>Barnard's Star</a><a href='#wise0855'>WISE 0855</a>
<a href='{REPO}/blob/main/report/hipparchus_scientific_report.pdf'>Report (PDF)</a>
<a href='{REPO}/blob/main/presentation/hipparchus_7_slides.pdf'>Slides (PDF)</a>
<a href='{REPO}/blob/main/video/hipparchus_demo_30s.mp4'>Video</a><a href='{REPO}'>Code</a></nav>
</header>
{''.join(sections)}
<footer>Team AITHENOVA, NASA Space Apps Challenge 2026 (Planet X and SPHEREx). Data: NASA SPHEREx via NASA/IPAC
Infrared Science Archive. Independent project, not endorsed by NASA. The images and numbers come from real SPHEREx
data; no simulated value appears on this page (the SIMULATED injection-recovery test is only in the report).
AI tools were used for the graphics, the demo video, cross-checking NASA/IRSA references and as a coding assistant;
all code was run and tested by the author. Built by <code>backend/scripts/make_judge_site.py</code> at commit {esc(commit)}.</footer>
</main></body></html>
"""
    (OUT / "index.html").write_text(page)
    print("wrote", OUT / "index.html", sorted(p.name for p in (OUT / "img").iterdir()))


if __name__ == "__main__":
    main()
