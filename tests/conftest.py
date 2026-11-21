import pytest

from devicelab import adapters, db, pool

INV = {
    "hosts": [
        {"name": "h1", "site": "sd", "max_devices": 4},
        {"name": "h2", "site": "sd", "max_devices": 4},
    ],
    "devices": [
        {"serial": "A1", "host": "h1", "model": "gen1", "tags": ["fp16"]},
        {"serial": "A2", "host": "h1", "model": "gen2", "tags": ["int8", "fp16"]},
        {"serial": "A3", "host": "h2", "model": "gen2", "tags": ["int8"]},
        {"serial": "A4", "host": "h2", "model": "gen2", "tags": ["int8"]},
    ],
}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "pool.db"))
    pool.load_inventory(c, INV)
    return c


@pytest.fixture
def sim():
    return adapters.SimAdapter()
