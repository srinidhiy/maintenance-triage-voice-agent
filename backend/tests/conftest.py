import copy
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import storage
from main import app

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def _load_seed() -> dict:
    seed = {}
    for key in ["buildings", "travel_times", "tenants", "tickets", "oncall", "alerts"]:
        with open(os.path.join(DATA_DIR, f"{key}.json")) as f:
            seed[key] = json.load(f)
    return seed

_SEED = _load_seed()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_storage(monkeypatch):
    # Mock save BEFORE resetting state so _recompute_schedule in startup
    # doesn't write to the real JSON files.
    monkeypatch.setattr(storage, "save", lambda key: None)
    for key, val in _SEED.items():
        storage._store[key] = copy.deepcopy(val)
    storage.set_travel_blocks([])
