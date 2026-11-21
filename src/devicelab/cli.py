import argparse
import json
import sys
import time

from . import adapters, capacity, db, events, hostcheck, pool, report


def _adapter(args):
    cfg = None
    if args.inventory:
        with open(args.inventory) as fh:
            cfg = json.load(fh).get("adapter")
    return adapters.from_config(cfg)


def _inv(path):
    with open(path) as fh:
        return json.load(fh)


def cmd_init(args, conn):
    inv = pool.load_inventory(conn, args.inventory)
    print(f"loaded {len(inv['hosts'])} hosts, {len(inv['devices'])} devices into {args.db}")


def cmd_status(args, conn):
    print(f"{'host':<10} {'state':<9} {'free':>4} {'leased':>6} {'quarantined':>11}")
    for r in report.status(conn):
        print(f"{r['host']:<10} {r['host_status']:<9} {r['free']:>4} {r['leased']:>6} {r['quarantined']:>11}")


def cmd_probe(args, conn):
    adapter = _adapter(args)
    inv = _inv(args.inventory)
    out = []
    now = time.time()
    for h in inv["hosts"]:
        for name, ok, detail in hostcheck.run_checks(h.get("checks", {})):
            pool.record_host(conn, h["name"], ok, f"{name}: {detail}", now)
            out.append(
                events.hec_event(h["name"], "health", {"kind": "host", "check": name, "ok": ok, "detail": detail}, now)
            )
            print(f"{'ok  ' if ok else 'FAIL'} host {h['name']} {name}: {detail}")
    for row in conn.execute("SELECT serial, host, state FROM devices WHERE state!='quarantined' ORDER BY serial").fetchall():
        ok, detail = adapter.probe(row["serial"])
        pool.record_probe(conn, row["serial"], ok, detail, now)
        out.append(
            events.hec_event(
                row["host"], "health", {"kind": "device", "serial": row["serial"], "ok": ok, "detail": detail}, now
            )
        )
        print(f"{'ok  ' if ok else 'FAIL'} device {row['serial']}: {detail}")
    if args.events:
        events.to_file(args.events, out)
    q = conn.execute("SELECT serial FROM devices WHERE state='quarantined' ORDER BY serial").fetchall()
    if q:
        print("quarantined:", ", ".join(r["serial"] for r in q))


def cmd_lease(args, conn):
    lease = pool.acquire(conn, args.owner, _adapter(args), args.model, args.tag, args.ttl)
    if lease is None:
        print("no healthy free device matches", file=sys.stderr)
        return 1
    print(json.dumps(lease))


def cmd_release(args, conn):
    if not pool.release(conn, args.lease_id):
        print("no active lease with that id", file=sys.stderr)
        return 1
    print(f"released lease {args.lease_id}")


def cmd_reap(args, conn):
    done = pool.reap(conn)
    for r in done:
        print(f"expired lease {r['id']} on {r['serial']} (owner {r['owner']})")
    print(f"{len(done)} expired")


def cmd_unquarantine(args, conn):
    if not pool.unquarantine(conn, args.serial):
        print(f"{args.serial} is not quarantined", file=sys.stderr)
        return 1
    print(f"{args.serial} back in the pool")


def cmd_report(args, conn):
    now = time.time()
    print(f"utilization, last {args.hours}h")
    for r in report.utilization(conn, now - args.hours * 3600, now):
        print(f"  {r['model']:<8} {r['devices']:>3} devices  {r['busy_pct']:>5}% leased")
    print("least healthy")
    for r in report.flaky(conn):
        print(f"  {r['kind']:<6} {r['subject']:<10} {r['failures']}/{r['probes']} failed ({r['fail_pct']}%)")


def cmd_plan(args, conn):
    res = capacity.plan(
        args.jobs_per_day,
        args.job_minutes,
        args.target_util,
        args.peak,
        args.spare_pct,
        args.devices_per_host,
        args.spare_hosts,
        args.existing,
    )
    print(json.dumps(res))


def cmd_serve(args, conn):
    from . import api

    srv = api.make_server(args.db, _adapter(args), args.bind, args.port)
    print(f"listening on {args.bind}:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_demo(args, conn):
    from . import demo

    demo.run()


def main(argv=None):
    p = argparse.ArgumentParser(prog="devicelab", description="Device lab pool, health and capacity tools")
    p.add_argument("--db", default="devicelab.db", help="SQLite file (default devicelab.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, inventory=False, **kw):
        sp = sub.add_parser(name, **kw)
        sp.set_defaults(fn=fn)
        if inventory:
            sp.add_argument("--inventory", default="examples/inventory.json")
        return sp

    add("init", cmd_init, True, help="load hosts and devices from an inventory file")
    add("status", cmd_status, help="devices per host by state")
    sp = add("probe", cmd_probe, True, help="probe hosts and devices, quarantine after 3 failures in a row")
    sp.add_argument("--events", help="append Splunk HEC JSON lines to this file")
    sp = add("lease", cmd_lease, True, help="lease a healthy free device")
    sp.add_argument("owner")
    sp.add_argument("--model")
    sp.add_argument("--tag")
    sp.add_argument("--ttl", type=int, default=3600)
    sp = add("release", cmd_release, help="release a lease")
    sp.add_argument("lease_id", type=int)
    add("reap", cmd_reap, help="end expired leases")
    sp = add("unquarantine", cmd_unquarantine, help="return a repaired device to the pool")
    sp.add_argument("serial")
    sp = add("report", cmd_report, help="utilization and least healthy hosts and devices")
    sp.add_argument("--hours", type=float, default=24)
    sp = add("plan", cmd_plan, help="capacity for a new hardware generation")
    sp.add_argument("--jobs-per-day", type=float, required=True)
    sp.add_argument("--job-minutes", type=float, required=True)
    sp.add_argument("--target-util", type=float, default=0.7)
    sp.add_argument("--peak", type=float, default=1.0)
    sp.add_argument("--spare-pct", type=float, default=5.0)
    sp.add_argument("--devices-per-host", type=int, default=4)
    sp.add_argument("--spare-hosts", type=int, default=1)
    sp.add_argument("--existing", type=int, default=0)
    sp = add("serve", cmd_serve, True, help="run the REST API")
    sp.add_argument("--bind", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8080)
    add("demo", cmd_demo, help="scripted scenario on a throwaway database")

    args = p.parse_args(argv)
    conn = db.connect(args.db) if args.cmd not in ("plan", "demo") else None
    try:
        return args.fn(args, conn) or 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn:
            conn.close()
