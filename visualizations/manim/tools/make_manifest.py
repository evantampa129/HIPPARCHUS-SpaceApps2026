"""Write MANIFEST.json: scene, labels, evidence files with SHA-256, outputs, duration."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "scenes"))
sys.path.insert(0, str(HERE))

from hviz import data as D  # noqa: E402
from registry import SCENES  # noqa: E402

WEB = ROOT / "docs" / "media" / "manim"


def duration(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out), 3)


def entry(path):
    if not path.exists():
        return None
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": D.sha256(path)}


def main():
    rows = []
    for mod, cls in SCENES:
        m = importlib.import_module(mod)
        scene = getattr(m, cls)
        evidence = list(m.EVIDENCE)
        extra = []
        if mod in ("m03_aperture", "m04_epsf") and D.PIXELS.exists():
            extra.append(entry(D.PIXELS) | {"from": "tools/extract_pixels.py (real cached cutout, checksum-checked)"})
        mp4 = HERE / "renders" / f"{mod}.mp4"
        rows.append({
            "scene": scene.SCENE_ID, "module": f"scenes/{mod}.py", "class": cls, "title": scene.TITLE,
            "labels": list(scene.LABELS), "source_line": scene.SOURCE,
            "evidence": D.evidence_files_used(evidence), "derived_inputs": extra,
            "outputs": {"mp4": entry(mp4), "still_png": entry(HERE / "renders" / f"{mod}.png"),
                        "web_mp4": entry(WEB / f"{mod}.mp4"), "web_poster_png": entry(WEB / f"{mod}_poster.png")},
            "duration_s": duration(mp4) if mp4.exists() else None,
            "video": "1920x1080, 30 fps, H.264 (yuv420p), no audio; web copy 1280x720",
        })
    out = {"what": "HIPPARCHUS Manim scenes M01-M10", "label_types": list(__import__("hviz.style").style.LABELS),
           "scenes": rows}
    (HERE / "MANIFEST.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote", HERE / "MANIFEST.json")


if __name__ == "__main__":
    main()
