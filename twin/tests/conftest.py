import os
import sys
from pathlib import Path

import pytest

os.environ["LARMOR_ASSISTANT_WARM"] = "0"   # never start or warm the local model during tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nmr_twin.context import load_context  # noqa: E402
from nmr_twin.service import golden_path  # noqa: E402


@pytest.fixture(scope="session")
def ctx():
    return load_context()


@pytest.fixture()
def twin(ctx):
    return golden_path(ctx)
