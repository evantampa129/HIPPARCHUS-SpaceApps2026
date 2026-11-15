"""Write submission/FINAL_CLAIMS_AND_ASSETS.json from the evidence files.

    python scripts/make_claims_registry.py
"""

import json

from hipparchus import claims

out = claims.ROOT / "submission" / "FINAL_CLAIMS_AND_ASSETS.json"
reg = claims.build()
out.write_text(json.dumps(reg, indent=1, ensure_ascii=False) + "\n")
for c in reg["claims"]:
    print(f"{c['id']:32s} {c['display']!s:10s} {', '.join(c['quoted_in'])}")
print("wrote", out)
