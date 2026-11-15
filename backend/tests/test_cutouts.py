"""The cutout cache must never hand back a file that differs from what was downloaded."""

import json

import pytest

from hipparchus import cutouts


def test_cache_key_depends_on_every_parameter():
    base = cutouts._key("https://x/a.fits", 1.0, 2.0, 0.05)
    assert base == cutouts._key("https://x/a.fits", 1.0, 2.0, 0.05)
    assert base != cutouts._key("https://x/a.fits", 1.0, 2.0, 0.06)
    assert base != cutouts._key("https://x/a.fits", 1.0001, 2.0, 0.05)


def test_corrupted_cache_file_is_not_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(cutouts, "CACHE_DIR", tmp_path)
    key = cutouts._key("https://example.invalid/a.fits", 1.0, 2.0, 0.05)
    (tmp_path / f"{key}.fits").write_bytes(b"SIMPLE  = T  truncated")
    (tmp_path / f"{key}.json").write_text(json.dumps({"url": "u", "sha256": "0" * 64, "bytes": 1}))
    # The checksum does not match, so fetch must try to download again rather
    # than return the bad file. The host does not exist, so that fails loudly.
    with pytest.raises(RuntimeError):
        cutouts.fetch("https://example.invalid/a.fits", 1.0, 2.0, 0.05, retries=0, timeout=2)
