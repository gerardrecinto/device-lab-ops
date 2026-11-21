import sqlite3
import threading

import pytest
from conftest import INV

from devicelab import adapters, db, pool


def test_acquire_filters_by_model_and_tag(conn, sim):
    assert pool.acquire(conn, "j", sim, model="gen1")["serial"] == "A1"
    assert pool.acquire(conn, "j", sim, tag="fp16")["serial"] == "A2"
    assert pool.acquire(conn, "j", sim, model="gen3") is None


def test_tag_match_is_exact_not_substring(conn, sim):
    pool.load_inventory(
        conn,
        {
            "hosts": INV["hosts"],
            "devices": INV["devices"] + [{"serial": "A5", "host": "h2", "model": "gen2", "tags": ["int8x"]}],
        },
    )
    got = {pool.acquire(conn, "j", sim, tag="int8")["serial"] for _ in range(3)}
    assert "A5" not in got


def test_two_active_leases_on_one_device_are_rejected_by_the_database(conn):
    now = 100.0
    conn.execute("INSERT INTO leases(serial, owner, started, expires) VALUES('A1','a',?,?)", (now, now + 10))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO leases(serial, owner, started, expires) VALUES('A1','b',?,?)", (now, now + 10))


def test_concurrent_callers_never_share_a_device(tmp_path):
    path = str(tmp_path / "race.db")
    c = db.connect(path)
    pool.load_inventory(c, INV)
    results, lock = [], threading.Lock()

    def worker(i):
        wc = db.connect(path)
        lease = pool.acquire(wc, f"job-{i}", adapters.SimAdapter(), now=1000.0)
        with lock:
            results.append(lease)
        wc.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    won = [r["serial"] for r in results if r]
    assert len(won) == 4 and len(set(won)) == 4
    assert sum(1 for r in results if r is None) == 8


def test_bad_device_is_skipped_and_counted(conn):
    sim = adapters.SimAdapter({"A1": 99})
    lease = pool.acquire(conn, "j", sim, now=10.0)
    assert lease["serial"] == "A2"
    row = conn.execute("SELECT fail_streak FROM devices WHERE serial='A1'").fetchone()
    assert row["fail_streak"] == 1


def test_three_failures_quarantine_and_end_the_lease(conn, sim):
    lease = pool.acquire(conn, "j", sim, model="gen1", now=0.0)
    for i in range(3):
        pool.record_probe(conn, "A1", False, "dead", now=10.0 + i)
    dev = conn.execute("SELECT state FROM devices WHERE serial='A1'").fetchone()
    lse = conn.execute("SELECT released, reason FROM leases WHERE id=?", (lease["id"],)).fetchone()
    assert dev["state"] == "quarantined"
    assert lse["reason"] == "quarantined" and lse["released"] is not None
    assert pool.acquire(conn, "k", sim, model="gen1", now=20.0) is None


def test_a_passing_probe_does_not_unquarantine(conn):
    for i in range(3):
        pool.record_probe(conn, "A1", False, "dead", now=float(i))
    pool.record_probe(conn, "A1", True, "ok", now=5.0)
    assert conn.execute("SELECT state FROM devices WHERE serial='A1'").fetchone()["state"] == "quarantined"
    assert pool.unquarantine(conn, "A1") is True
    assert pool.unquarantine(conn, "A1") is False


def test_success_resets_the_streak(conn):
    pool.record_probe(conn, "A1", False, "x", now=1.0)
    pool.record_probe(conn, "A1", False, "x", now=2.0)
    pool.record_probe(conn, "A1", True, "ok", now=3.0)
    pool.record_probe(conn, "A1", False, "x", now=4.0)
    assert conn.execute("SELECT state, fail_streak FROM devices WHERE serial='A1'").fetchone()["state"] == "free"


def test_reap_frees_only_expired_leases(conn, sim):
    short = pool.acquire(conn, "short", sim, model="gen1", ttl=60, now=0.0)
    long = pool.acquire(conn, "long", sim, model="gen2", ttl=600, now=0.0)
    out = pool.reap(conn, now=100.0)
    assert [r["id"] for r in out] == [short["id"]]
    assert conn.execute("SELECT state FROM devices WHERE serial=?", (long["serial"],)).fetchone()["state"] == "leased"
    assert conn.execute("SELECT state FROM devices WHERE serial='A1'").fetchone()["state"] == "free"


def test_release_twice_is_a_noop(conn, sim):
    lease = pool.acquire(conn, "j", sim, now=0.0)
    assert pool.release(conn, lease["id"], now=1.0) is True
    assert pool.release(conn, lease["id"], now=2.0) is False


def test_degraded_host_gets_no_new_leases(conn, sim):
    pool.record_host(conn, "h1", False, "nfs hung", now=1.0)
    assert pool.acquire(conn, "j", sim, model="gen1") is None
    pool.record_host(conn, "h1", True, "nfs ok", now=2.0)
    assert pool.acquire(conn, "j", sim, model="gen1")["serial"] == "A1"


def test_inventory_rejects_more_devices_than_host_slots(conn):
    bad = {"hosts": [{"name": "h1", "site": "sd", "max_devices": 1}], "devices": INV["devices"][:2]}
    with pytest.raises(ValueError, match="max_devices"):
        pool.load_inventory(conn, bad)


def test_reload_keeps_lease_state(conn, sim):
    pool.acquire(conn, "j", sim, model="gen1")
    pool.load_inventory(conn, INV)
    assert conn.execute("SELECT state FROM devices WHERE serial='A1'").fetchone()["state"] == "leased"
