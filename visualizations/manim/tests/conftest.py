import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scenes"))
EVID = HERE.parents[1] / "submission" / "evidence"


@pytest.fixture(scope="session")
def raw():
    """Evidence JSON read directly, independent of the library's loader."""
    return lambda name: json.loads((EVID / name).read_text())
