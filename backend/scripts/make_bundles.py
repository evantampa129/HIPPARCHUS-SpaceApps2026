"""Build the mini reports and reproduction bundles from the published evidence.

    cd backend
    python scripts/make_bundles.py                 # reports (HTML, + PDF if Chrome is installed) and zips
    python scripts/make_bundles.py --verify        # then replay each bundle against data/cache
    python scripts/make_bundles.py --verify --network   # replay against IRSA itself (slow, opt-in)

Nothing here touches the archive unless --network is given.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hipparchus import bundle, minireport  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*", default=list(bundle.CASES))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--network", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)

    # reports first: the bundles copy the same HTML
    for c, v in minireport.export(a.cases, pdf=not a.no_pdf).items():
        print(c, v["html"], v["pdf"] or "(HTML only: no headless Chrome/Chromium found)")
    for c in a.cases:
        print(bundle.build(c))
    if a.verify:
        for c in a.cases:
            r = bundle.verify(bundle.BUNDLE_DIR / f"{c}.zip", network=a.network)
            print(c, "OK" if r["ok"] else "NOT OK", json.dumps(r["summary"]))
            for row in r["items"]:
                if row["status"] == "DRIFT":
                    print("  DRIFT", row["url"], row["expected_sha256"], "->", row["got_sha256"])


if __name__ == "__main__":
    main()
