"""Rebuild the evidence files in submission/evidence/ from the archive.

    cd backend && python scripts/reproduce_evidence.py

We reuse cutouts already in data/cache once their checksum checks out, and
download missing ones again from IRSA. The output contains every
identifier, checksum, setting and number, so the files can be compared
line by line with the committed ones.
"""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from hipparchus.api import TARGETS, _config, _public  # noqa: E402
from hipparchus.pipeline import analyze  # noqa: E402

OUT = ROOT / "submission" / "evidence"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "code_commit": commit, "config": _config(), "cases": []}
    for t in TARGETS:
        r = analyze(t["ra"], t["dec"], t["detector"])
        r["target"] = t
        r["config"] = _config()
        pub = _public(r)
        path = OUT / f"{t['id']}_{t['detector'].lower()}.json"  # lower-case file names
        body = json.dumps(pub, indent=1)
        path.write_text(body)
        changed = [c for c in pub["comparisons"] if c["changed"]]
        manifest["cases"].append({
            "target": t["name"], "ra": t["ra"], "dec": t["dec"], "detector": t["detector"],
            "archive_status": pub["archive_status"],
            "archive_queries": pub["archive_queries"],
            "epochs": pub["n_epochs"], "usable_epochs": pub["n_usable"],
            "valid_comparisons": len(pub["comparisons"]), "changes_over_5_sigma": len(changed),
            "refused_pairs": pub["refused_pairs"],
            "failed_downloads": len(pub["failed_downloads"]),
            "file": str(path.relative_to(ROOT)), "file_sha256": hashlib.sha256(body.encode()).hexdigest(),
        })
        print(t["name"], manifest["cases"][-1]["usable_epochs"], len(pub["comparisons"]), len(changed))
    (OUT / "evidence_manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
