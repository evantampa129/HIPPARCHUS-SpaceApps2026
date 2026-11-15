"""Check the three preset positions against SIMBAD and Gaia DR3 (live, via mirrors).

Writes submission/evidence/catalog_match.json. Measurements are not touched:
this only records whether each preset is on the right star, how far off it
is, and which Gaia stars fall inside the 2-pixel photometry aperture.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hipparchus import api, catalogs  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "submission" / "evidence" / "catalog_match.json"
# SIMBAD main identifiers of the presets.
SIMBAD_NAME = {"rw_aur": "V* RW Aur", "barnard": "NAME Barnard's star",
               "wise0855": "WISEA J085510.74-071442.5"}
# Barnard's Star moved ~270" since SIMBAD's epoch-2000 position, so its cone
# has to be wider than 120".
SIMBAD_RADIUS = 360.0

result = {"queried_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
          "note": "CDS Strasbourg offline after a cybersecurity incident (cds.unistra.fr notice, 9 Nov 2026); "
                  "mirrors used as recommended by CDS. Gaia DR3 epoch 2016.0 and SIMBAD epoch 2000.0 positions "
                  f"moved to {catalogs.SPHEREX_EPOCH} with their proper motions.",
          "targets": {}}
for t in api.TARGETS:
    sim = catalogs.simbad_cone(t["ra"], t["dec"], SIMBAD_RADIUS)
    gaia = catalogs.gaia_cone(t["ra"], t["dec"])
    m = catalogs.match(SIMBAD_NAME[t["id"]], t["ra"], t["dec"], sim, gaia)
    m["simbad_service"] = {k: v for k, v in sim.items() if k != "rows"} | {"n_rows": len(sim["rows"])}
    m["gaia_service"] = {k: v for k, v in gaia.items() if k != "rows"} | {"n_rows": len(gaia["rows"])}
    result["targets"][t["id"]] = m
    s, g = m["simbad"], m["gaia_counterpart"]
    print(t["id"], "| SIMBAD:", s and s["main_id"], s and s["otype"],
          "| offset", m["preset_offset_arcsec"] and round(m["preset_offset_arcsec"], 2), "\"",
          "| Gaia:", g and g["source_id"], g and g["g"],
          "| in aperture:", [(a["source_id"], a["g"], round(a["sep_from_target_arcsec"], 2)) for a in m["gaia_in_aperture"]],
          "|", sim["status"], gaia["status"])
OUT.write_text(json.dumps(result, indent=1, default=str) + "\n")
print("wrote", OUT)
