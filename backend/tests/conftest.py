import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.repositories.data_repo import load_bundle


@pytest.fixture(scope="session")
def bundle():
    """Uses the already-seeded demo database (run `python -m app.services.seed`
    before running tests, same as the demo does)."""
    return load_bundle()
