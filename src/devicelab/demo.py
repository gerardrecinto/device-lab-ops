"""A scripted scenario on a fake clock, so the output is identical on every run. The Pages site shows this output."""

from . import adapters, capacity, db, pool, report

T0 = 1_000_000.0
INVENTORY = {
    "hosts": [
        {"name": "x86-01", "site": "san-diego", "max_devices": 4},
        {"name": "x86-02", "site": "san-diego", "max_devices": 4},
    ],
    "devices": [
        {
            "serial": f"SN-{i:04d}",
            "host": "x86-01" if i <= 4 else "x86-02",
            "model": "gen2" if i % 2 else "gen1",
            "tags": ["int8"] if i % 2 else ["fp16"],
        }
        for i in range(1, 9)
    ],
}


def run():
    conn = db.connect(":memory:")
    pool.load_inventory(conn, INVENTORY)
    adapter = adapters.SimAdapter({"SN-0003": 99})  # this device never answers
    t = T0

    print("1. Three jobs ask for a gen2 device; the pool probes each candidate before it hands one out")
    leases = {}
    for owner in ("job-101", "job-102", "job-103"):
        t += 60
        lease = pool.acquire(conn, owner, adapter, model="gen2", ttl=900, now=t)
        leases[owner] = lease
        print(f"   {owner} -> {lease['serial'] if lease else 'none'}")
    streak = conn.execute("SELECT fail_streak FROM devices WHERE serial='SN-0003'").fetchone()[0]
    print(f"   SN-0003 failed its probe {streak} time and was skipped; failing devices sort last after that")

    print("2. Two more health probes fail; three in a row quarantines SN-0003")
    for _ in range(2):
        t += 30
        ok, detail = adapter.probe("SN-0003")
        pool.record_probe(conn, "SN-0003", ok, detail, t)
    state = conn.execute("SELECT state, fail_streak FROM devices WHERE serial='SN-0003'").fetchone()
    print(f"   SN-0003 state={state['state']} fail_streak={state['fail_streak']}")

    print("3. job-101 and job-103 release; job-102 crashes. 20 minutes later the reaper ends its lease")
    for owner in ("job-101", "job-103"):
        pool.release(conn, leases[owner]["id"], t)
    t += 1200
    for r in pool.reap(conn, t):
        print(f"   expired lease {r['id']} on {r['serial']} (owner {r['owner']})")

    print("4. Pool by host after the reaper")
    for r in report.status(conn):
        print(f"   {r['host']}: free={r['free']} leased={r['leased']} quarantined={r['quarantined']}")

    print("5. Least healthy")
    for r in report.flaky(conn):
        print(f"   {r['kind']} {r['subject']}: {r['failures']}/{r['probes']} probes failed")

    print("6. Next hardware cycle: 600 jobs a day, 25 minutes each, 2x peak, 70% target use, 4 devices per host")
    res = capacity.plan(600, 25, 0.7, 2.0, 5.0, 4, 1, existing_devices=8)
    print(f"   {res['working_devices']} working devices, {res['devices']} with spares, {res['hosts']} hosts")
    print(f"   buy {res['to_buy']} (8 on hand)")
