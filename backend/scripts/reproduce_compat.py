"""Spectral-response overlap and compatibility graph for the three targets.

Reads only the published evidence files, so it runs offline in a few seconds:

    python scripts/reproduce_compat.py

Writes submission/evidence/compat_check.json and report/figures/compat_graph.png.
"""

from __future__ import annotations

import json
from pathlib import Path

from hipparchus import compat
from hipparchus.compare import MAX_DLAMBDA_FRACTION

ROOT = Path(__file__).resolve().parents[2]
EV = ROOT / "submission" / "evidence"
OUT = EV / "compat_check.json"
FIG = ROOT / "report" / "figures" / "compat_graph.png"
TARGETS = {"rw_aur": "rw_aur_spherex-d1.json", "barnard": "barnard_spherex-d6.json",
           "wise0855": "wise0855_spherex-d6.json"}
THRESHOLDS = (0.5, 0.7)


def main():
    result = {
        "assumption": ("Each exposure's response at the star is one channel centred on the wavelength at the "
                       "star, with the channel width as full width; we try a Gaussian (FWHM = width) and a "
                       "top-hat. Wavelengths are the published (legacy WCS) ones."),
        "rule": f"|dλ| <= {MAX_DLAMBDA_FRACTION} × channel width",
        "overlap_at_rule_limit": {s: compat.overlap_at_rule_limit(s) for s in compat.SHAPES},
        "targets": {},
    }
    graphs = {}
    for key, fname in TARGETS.items():
        ev = json.loads((EV / fname).read_text())
        rows = compat.pair_table(ev)
        g = compat.graph(ev, rows)
        graphs[key] = g
        pub = [r for r in rows if r["published_comparison"]]
        # Pairs refused only for wavelength, between two usable epochs: these are
        # the ones where a softer rule could have changed the answer.
        usable = {e["obs_id"] for e in ev["epochs"] if e["usable"]}
        wl_only = [r for r in rows if r["a"] in usable and r["b"] in usable
                   and r["refusal_codes"] == ["wavelength_mismatch"]]
        # Our pair verdict, rebuilt from the evidence, must give back exactly
        # the published comparisons (refusals at the pixel stage aside).
        rebuilt = [r for r in rows if not r["refusal_codes"] and not r["same_visit"]]
        assert len(g["edges"]) == len(ev["comparisons"])
        result["targets"][key] = {
            "graph_summary": g["summary"],
            "published_refusal_counts": ev["refused_pairs"],
            "rebuilt_comparable_pairs": len(rebuilt),
            "published_pairs": len(pub),
            "published_min_overlap": {s: min((r[f"overlap_{s}"] for r in pub), default=None)
                                      for s in compat.SHAPES},
            "published_pairs_overlap_below_0.5": {
                s: sum(r[f"overlap_{s}"] < 0.5 for r in pub) for s in compat.SHAPES},
            "usable_pairs_refused_only_for_wavelength": len(wl_only),
            "of_which_overlap_ge": {f"{t}": {s: sum(r[f"overlap_{s}"] >= t for r in wl_only)
                                             for s in compat.SHAPES} for t in THRESHOLDS},
            "confusion_all_pairs": {f"{s}@{t}": compat.confusion(rows, t, s)
                                    for s in compat.SHAPES for t in THRESHOLDS},
        }
        t = result["targets"][key]
        print(f"{key}: {g['summary']['n_nodes']} epochs, {g['summary']['n_usable']} usable, "
              f"{g['summary']['n_edges']} edges (rebuilt {len(rebuilt)}), "
              f"min overlap of published pairs {t['published_min_overlap']}, "
              f"usable pairs refused only for λ: {len(wl_only)} -> high overlap {t['of_which_overlap_ge']}")
    result["graphs"] = graphs
    OUT.write_text(json.dumps(result, indent=1))
    print("wrote", OUT)
    figure(graphs)


def figure(graphs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, (key, title) in zip(axes, [("rw_aur", "RW Aur, detector 1"), ("wise0855", "WISE 0855, detector 6")]):
        g = graphs[key]
        pos = {n["id"]: (n["mjd"], n["wavelength_um"]) for n in g["nodes"]}
        for e in g["edges"]:
            (x1, y1), (x2, y2) = pos[e["a"]], pos[e["b"]]
            ax.plot([x1, x2], [y1, y2], "-", color="tab:blue", lw=0.8, alpha=0.6)
        for usable, style, lab in ((True, dict(c="tab:green", s=22), "usable epoch"),
                                   (False, dict(c="lightgray", s=14), "flagged epoch")):
            pts = [pos[n["id"]] for n in g["nodes"] if n["usable"] == usable]
            if pts:
                ax.scatter(*zip(*pts), zorder=3, label=lab, **style)
        ax.plot([], [], "-", color="tab:blue", label=f"compared pair ({len(g['edges'])})")
        ax.set_xlabel("MJD"), ax.set_ylabel("wavelength at the star [µm]")
        ax.set_title(f"{title}: {g['summary']['n_nodes']} epochs, {len(g['edges'])} pairs", fontsize=10)
        ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False)
    fig.suptitle("Observation compatibility graph (edges = pairs that pass every check)", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG, dpi=150)
    print("wrote", FIG)


if __name__ == "__main__":
    main()
