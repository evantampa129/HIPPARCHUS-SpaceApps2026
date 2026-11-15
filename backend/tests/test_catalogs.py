"""Catalogue matching logic, offline (the network part is exercised by scripts/reproduce_catalogs.py)."""

from hipparchus import catalogs as c


def test_barnard_proper_motion_moves_it_by_a_hundred_arcsec():
    # Barnard's Star, Gaia DR3: pmra -801.6, pmdec 10362.4 mas/yr. Ten years
    # from 2016 to 2026 should move it ~104" north, i.e. ~17 SPHEREx pixels.
    ra, dec = 269.4486, 4.7394
    ra2, dec2 = c.propagate(ra, dec, -801.6, 10362.4, 2016.0, 2026.0)
    assert abs(c.sep_arcsec(ra, dec, ra2, dec2) - 103.9) < 0.5
    assert dec2 > dec


def test_missing_proper_motion_leaves_position_alone():
    assert c.propagate(10.0, 20.0, None, 5.0, 2000.0, 2026.0) == (10.0, 20.0)


def test_match_picks_named_object_and_lists_aperture_neighbours():
    simbad = {"rows": [
        {"main_id": "Other star", "ra": 50.0001, "dec": 10.0, "pmra": None, "pmdec": None, "otype": "*"},
        {"main_id": "V* Test", "ra": 50.0005, "dec": 10.0, "pmra": None, "pmdec": None, "otype": "TT*"},
    ]}
    gaia = {"rows": [
        {"source_id": "1", "ra": 50.0005, "dec": 10.0, "pmra": None, "pmdec": None, "g": 12.0},
        {"source_id": "2", "ra": 50.0005, "dec": 10.0025, "pmra": None, "pmdec": None, "g": 15.0},  # 9"
        {"source_id": "3", "ra": 50.0005, "dec": 10.01, "pmra": None, "pmdec": None, "g": 14.0},    # 36"
    ]}
    m = c.match("V* Test", 50.0, 10.0, simbad, gaia)
    assert m["simbad"]["main_id"] == "V* Test"          # by name, not the nearer star
    assert m["gaia_counterpart"]["source_id"] == "1"
    assert [s["source_id"] for s in m["gaia_in_aperture"]] == ["1", "2"]
    assert abs(m["preset_offset_arcsec"] - 1.77) < 0.05


def test_no_catalogue_answer_means_no_match():
    m = c.match("V* Test", 50.0, 10.0, {"rows": []}, {"rows": []})
    assert m["simbad"] is None and m["gaia_counterpart"] is None and m["preset_offset_arcsec"] is None
