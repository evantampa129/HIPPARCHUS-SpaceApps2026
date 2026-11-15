"""Build every report figure from files committed in the repository.

    backend/.venv/bin/python report/figures/make_figures.py

Inputs: the real SPHEREx cutouts in backend/tests/fixtures and the evidence
JSON files in submission/evidence. Only the injection-recovery panel of
Figure 5 uses SIMULATED stars, and it says so on the figure itself.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from hipparchus import compare, quality  # noqa: E402

OUT = Path(__file__).parent
FX = ROOT / "backend" / "tests" / "fixtures"
EV = ROOT / "submission" / "evidence"
plt.rcParams.update({"font.size": 9, "font.family": "serif"})


def show(ax, img, title, cmap="gray", vmin=None, vmax=None, x=None, y=None):
    cm = plt.get_cmap(cmap).copy(); cm.set_bad("#999999")
    im = ax.imshow(np.ma.masked_invalid(img), origin="lower", cmap=cm, vmin=vmin, vmax=vmax, interpolation="nearest")
    if x is not None:
        ax.add_patch(plt.Circle((x, y), quality.APERTURE_PX, fill=False, color="#00a0e0", lw=1))
    ax.set_title(title); ax.set_xticks([]); ax.set_yticks([])
    return im


# Figure 1: the valid RW Aur pair, on a's pixel grid.
a = quality.load(str(FX / "rwaur_d1_2025.fits"), "2025W36_1A_0233_3", 76.956, 30.401)
b = quality.load(str(FX / "rwaur_d1_2026.fits"), "2026W37_1A_0234_3", 76.956, 30.401)
r = compare.compare(a, b)
arr = r["_arrays"]
lo, hi = np.nanpercentile(np.r_[arr["a"].ravel(), arr["b"].ravel()], [1, 99.9])
fig, axs = plt.subplots(1, 4, figsize=(7.2, 2.1), constrained_layout=True)
A = np.where(a.bad, np.nan, arr["a"])
show(axs[0], A, f"{a.date_obs[:10]}", vmin=lo, vmax=hi, x=a.x, y=a.y)
show(axs[1], arr["b"], f"{b.date_obs[:10]} (reprojected)", vmin=lo, vmax=hi, x=a.x, y=a.y)
lim = np.nanpercentile(np.abs(arr["diff"]), 99.5)
show(axs[2], arr["diff"], "difference (MJy/sr)", "RdBu_r", -lim, lim, a.x, a.y)
im = show(axs[3], arr["z"], r"significance ($\sigma$)", "RdBu_r", -5, 5, a.x, a.y)
fig.colorbar(im, ax=axs[3], shrink=0.8)
fig.savefig(OUT / "rwaur_pair.pdf"); plt.close(fig)

# Figure 2: a rejected Barnard's Star epoch with its flagged pixels.
e = quality.load(str(FX / "barnard_d6.fits"), "2025W33_2C_0321_1", 269.4463, 4.7667)
fig, axs = plt.subplots(1, 2, figsize=(4.8, 2.3), constrained_layout=True)
show(axs[0], np.arcsinh(e.image), "image (asinh)", x=e.x, y=e.y)
show(axs[1], e.bad.astype(float), "pixels with rejecting flags", "Reds", 0, 1, e.x, e.y)
fig.savefig(OUT / "barnard_flags.pdf"); plt.close(fig)

# Figure 3: flux ratio of every valid RW Aur pair against its control star.
rw = json.loads((EV / "rw_aur_spherex-d1.json").read_text())
fig, ax = plt.subplots(figsize=(4.6, 2.8), constrained_layout=True)
for c in rw["comparisons"]:
    ax.scatter(c["dt_days"], c["flux_ratio"], color="#c0392b", zorder=3)
    if c["control_star"]:
        ax.scatter(c["dt_days"], c["control_star"]["ratio"], color="#2c7fb8", marker="s", zorder=3)
ax.axhline(1, color="k", lw=0.6, ls=":")
ax.scatter([], [], color="#c0392b", label="RW Aur (target)")
ax.scatter([], [], color="#2c7fb8", marker="s", label="control star, same images")
ax.set_xlabel("time between epochs (days)"); ax.set_ylabel("flux ratio later / earlier")
ax.legend(frameon=False, fontsize=8)
fig.savefig(OUT / "rwaur_ratios.pdf"); plt.close(fig)

# Figure 4: what happened to every possible pair, per target.
cases = [("rw_aur_spherex-d1", "RW Aur D1"), ("wise0855_spherex-d6", "WISE 0855 D6"), ("barnard_spherex-d6", "Barnard D6")]
fig, ax = plt.subplots(figsize=(5.2, 2.4), constrained_layout=True)
for i, (f, name) in enumerate(cases):
    d = json.loads((EV / f"{f}.json").read_text())
    n = d["n_epochs"]; total = n * (n - 1) // 2
    valid = len(d["comparisons"]) + len(d["null_tests"])
    vals = [valid, total - valid]
    ax.barh(i, vals[0], color="#4fa36b"); ax.barh(i, vals[1], left=vals[0], color="#d9a441")
    ax.text(total + 20, i, f"{valid} valid / {total} pairs", va="center", fontsize=8)
ax.set_yticks(range(len(cases)), [c[1] for c in cases]); ax.set_xlabel("epoch pairs")
ax.set_xlim(0, ax.get_xlim()[1] * 1.35)
fig.savefig(OUT / "pair_outcomes.pdf"); plt.close(fig)
# Figure 5: is the error model right, and what can be detected?
val = json.loads((EV / "validation.json").read_text())
fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.5), constrained_layout=True)
# Left: spread of the blank-aperture significances per target, against the
# value of 1 that correct error bars would give.
names = {"rw_aur": "RW Aur", "wise0855": "WISE 0855", "barnard": "Barnard"}
rows = [(names[t["id"]], t["null_test"]) for t in val["targets"] if t["null_test"]["n"]]
rows.append(("all", val["all_targets"]["null_test"]))
ys = range(len(rows))
axs[0].barh(ys, [r["std"] for _, r in rows], color="#2c7fb8", height=0.55)
for i, (_, r) in enumerate(rows):
    axs[0].text(r["std"] + 0.03, i, f"{r['std']:.2f}  (n={r['n']})", va="center", fontsize=8)
axs[0].axvline(1, color="k", lw=0.8, ls=":")
axs[0].set_yticks(list(ys), [n for n, _ in rows]); axs[0].set_xlim(0, 1.6)
axs[0].set_xlabel(r"spread of blank-aperture significances (ideal 1)")
axs[0].set_title("null test, real images")
cur = val["all_targets"]["injection_SIMULATED"]
axs[1].plot([c["snr_injected"] for c in cur], [c["recovered_fraction"] for c in cur], "o-", color="#c0392b")
axs[1].axvline(compare.DETECTION_SIGMA, color="k", lw=0.6, ls=":"); axs[1].axhline(0.5, color="k", lw=0.6, ls=":")
axs[1].set_xlabel("injected S/N in the aperture"); axs[1].set_ylabel(r"fraction recovered at 5$\sigma$")
axs[1].set_title("injection-recovery: SIMULATED stars", color="#c0392b")
axs[1].text(0.97, 0.05, "SIMULATED", transform=axs[1].transAxes, ha="right", color="#c0392b", fontsize=12, alpha=0.6,
            weight="bold")
fig.savefig(OUT / "validation.pdf"); plt.close(fig)

# Figure 6: brightness against wavelength, coloured by date (real data).
fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.5), constrained_layout=True)
for ax, tid in zip(axs, ("rw_aur", "wise0855")):
    t = next(t for t in val["targets"] if t["id"] == tid)
    sp = t["spectrum"]
    from datetime import date
    days = np.array([(date.fromisoformat(p["date_obs"][:10]) - date(2025, 1, 1)).days for p in sp])
    sc = ax.scatter([p["wavelength_um"] for p in sp], [p["flux"] for p in sp], c=days, cmap="viridis", s=14, zorder=3)
    ax.errorbar([p["wavelength_um"] for p in sp], [p["flux"] for p in sp], yerr=[p["flux_err"] for p in sp],
                fmt="none", ecolor="#999999", lw=0.6, zorder=2)
    ax.set_xlabel(r"wavelength at the target ($\mu$m)"); ax.set_ylabel("aperture flux (MJy/sr summed)")
    ax.set_title(f"{t['name']} ({t['detector'][-2:]}), {len(sp)} usable epochs")
cb = fig.colorbar(sc, ax=axs[1], shrink=0.85); cb.set_label("days since 2025-01-01")
fig.savefig(OUT / "spectra.pdf"); plt.close(fig)
print("figures written to", OUT)
