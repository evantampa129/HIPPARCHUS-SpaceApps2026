from pathlib import Path

from hipparchus import archive

# A real response from IRSA's SIA service (spherex_dr1, around Barnard's Star),
# saved on 2026-11-15, so we can test the parser without a network connection.
FIXTURE = Path(__file__).parent / "fixtures" / "sia_dr1_barnard.xml"


def test_parse_real_votable():
    obs = archive._parse(FIXTURE.read_bytes(), "spherex_dr1")
    assert len(obs) > 100
    o = obs[0]
    # Every field we rely on later must come through with sensible units.
    assert o.detector.startswith("SPHEREx-D")
    assert 0.7 < o.em_min_um < o.em_max_um < 5.1   # SPHEREx covers about 0.75-5.0 um
    assert o.mjd_end > o.mjd_start > 60000          # exposures are from 2025 onwards
    assert o.access_url.startswith("https://irsa.ipac.caltech.edu/")
    assert o.doi == "10.26131/IRSA678"


def test_utc_conversion():
    obs = archive._parse(FIXTURE.read_bytes(), "spherex_dr1")
    # MJD 60902.86 falls on 15 August 2025 (the header of that file says DATE-OBS 2025-08-15).
    first = min(obs, key=lambda o: o.mjd_start)
    assert first.utc_mid.startswith("2025-08-15")


def test_partial_answer_does_not_overwrite_saved_listing(tmp_path, monkeypatch):
    # DR1 answers, QR3 fails: the result is "partial" and must not be cached,
    # or the offline fallback would later serve an incomplete listing.
    import httpx
    from hipparchus import archive
    monkeypatch.setattr(archive, "MANIFEST_DIR", tmp_path)
    body = FIXTURE.read_bytes()

    def fake_get(url, params, timeout):
        if params["COLLECTION"] == "spherex_qr3":
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(archive.httpx, "get", fake_get)
    monkeypatch.setattr(archive.time, "sleep", lambda s: None)
    m = archive.query(269.452, 4.693, retries=0)
    assert m["archive_status"] == "partial" and m["observations"]
    assert not list(tmp_path.iterdir())
