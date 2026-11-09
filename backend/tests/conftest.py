import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT_THRESHOLDS  # noqa: E402
from app.db import connect  # noqa: E402


@pytest.fixture
def cfg():
    return dict(DEFAULT_THRESHOLDS)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("GARMIN_API_KEY", "")
    monkeypatch.setenv("GARMIN_API_KEY_EXPIRES", "")
    return path


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()
