"""Every public number must still match the evidence and every output that quotes it."""

import json

import pytest

from hipparchus import claims

REG = claims.ROOT / "submission" / "FINAL_CLAIMS_AND_ASSETS.json"


def test_registry_is_up_to_date():
    # We rebuild from the evidence; a stale registry means someone re-ran an
    # analysis without regenerating it.
    assert json.loads(REG.read_text()) == json.loads(json.dumps(claims.build(), ensure_ascii=False))


@pytest.mark.parametrize("claim", claims.build()["claims"], ids=lambda c: c["id"])
def test_quoted_outputs_contain_the_number(claim):
    for path in claim["quoted_in"]:
        text = (claims.ROOT / path).read_text()
        assert claim["display"] in text, f"{claim['id']}={claim['display']} missing from {path}"


def test_every_claim_has_a_known_status():
    reg = claims.build()
    assert {c["status"] for c in reg["claims"]} <= set(reg["statuses"])
