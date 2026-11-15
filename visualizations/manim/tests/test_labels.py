"""Every scene carries its label badges and a source line on every frame, and shows its key numbers."""

import importlib

import pytest
from manim import tempconfig

from hviz.style import LABELS, all_texts
from registry import SCENES

# Text that must be on screen at the end of each scene (spaces are dropped by Manim's Text).
MUST_SHOW = {
    "M01AncientSky": ["HISTORICAL ILLUSTRATION", "RA 76.956°"],
    "M02Filters": ["MODEL (top-hat / Gaussian surrogate)", "COMPATIBLE: compared", "INCOMPATIBLE: refused", "55.6%"],
    "M03Aperture": ["80.33 ± 0.40", "aperture r = 2 px", "4–7 px"],
    "M04EPSF": ["χ²_red = 12.9", "8/8 within 2%"],
    "M05Fingerprint": ["24/24", "18/24", "34/34", "rule-based labels, not probabilities"],
    "M06Kleopatra": ["residuals ×60 for display", "observed", "predicted", "fitted"],
    "M07ShiftStack": ["SIMULATED", "HIPPARCHUS has not found Planet X."],
    "M08Falsification": ["COMPARISON REFUSED", "SUPPORTED CHANGE", "0/58", "×2.56"],
    "M09CompatGraph": ["8 edges of 1540 pairs", "27 edges of 990 pairs"],
    "M10SpectralTime": ["never a coadd"],
}


def squash(s):
    return "".join(s.split())


@pytest.mark.parametrize("mod,cls", SCENES)
def test_scene_labels_and_numbers(mod, cls):
    with tempconfig({"dry_run": True, "quality": "low_quality", "disable_caching": True, "verbosity": "ERROR"}):
        Scene = getattr(importlib.import_module(mod), cls)
        s = Scene()
        s.render()
    assert Scene.LABELS and all(l in LABELS for l in Scene.LABELS)
    # The chrome is a foreground mobject added in setup(), so it is on every frame.
    assert s.chrome in s.foreground_mobjects
    chrome_text = [squash(t) for t in all_texts([s.chrome])]
    for l in Scene.LABELS:
        assert squash(l) in chrome_text
    assert squash(Scene.SOURCE) in chrome_text and "HIPPARCHUS" in Scene.SOURCE
    shown = "\n".join(all_texts(s.mobjects + s.foreground_mobjects))
    for want in MUST_SHOW[cls]:
        assert squash(want) in shown, f"{cls}: {want!r} not on screen"
