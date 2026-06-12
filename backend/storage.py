import json
import os
from typing import List

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

_store: dict = {
    "buildings": [],
    "travel_times": [],
    "tenants": [],
    "tickets": [],
    "oncall": [],
    "alerts": [],
}

_travel_blocks: List[dict] = []


def load_all() -> None:
    for key in _store:
        path = os.path.join(DATA_DIR, f"{key}.json")
        with open(path, "r") as f:
            _store[key] = json.load(f)


def save(key: str) -> None:
    path = os.path.join(DATA_DIR, f"{key}.json")
    with open(path, "w") as f:
        json.dump(_store[key], f, indent=2, default=str)


def get(key: str) -> list:
    return _store[key]


def set_travel_blocks(blocks: List[dict]) -> None:
    global _travel_blocks
    _travel_blocks = blocks


def get_travel_blocks() -> List[dict]:
    return _travel_blocks
