"""Device pool: inventory, leases with expiry, health-gated acquire, quarantine."""

import json
import time

QUARANTINE_AFTER = 3


def load_inventory(conn, path_or_dict):
    """Insert or update hosts and devices. Safe to run again; it never touches lease state."""
    inv = path_or_dict
    if not isinstance(inv, dict):
        with open(path_or_dict) as fh:
            inv = json.load(fh)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for h in inv["hosts"]:
            conn.execute(
                "INSERT INTO hosts(name, site, max_devices) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET site=excluded.site, max_devices=excluded.max_devices",
                (h["name"], h["site"], h["max_devices"]),
            )
        per_host = {}
        for d in inv["devices"]:
            per_host[d["host"]] = per_host.get(d["host"], 0) + 1
        for h in inv["hosts"]:
            if per_host.get(h["name"], 0) > h["max_devices"]:
                raise ValueError(f"{h['name']} has {per_host[h['name']]} devices but max_devices is {h['max_devices']}")
        for d in inv["devices"]:
            conn.execute(
                "INSERT INTO devices(serial, host, model, tags) VALUES(?,?,?,?) "
                "ON CONFLICT(serial) DO UPDATE SET host=excluded.host, model=excluded.model, tags=excluded.tags",
                (d["serial"], d["host"], d["model"], ",".join(d.get("tags", []))),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return inv


def record_probe(conn, serial, ok, detail, now=None, threshold=QUARANTINE_AFTER):
    """Store a device probe. Three failures in a row quarantine the device and end its lease."""
    now = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO health(ts, subject, kind, ok, detail) VALUES(?,?,?,?,?)",
            (now, serial, "device", int(ok), detail),
        )
        if ok:
            conn.execute("UPDATE devices SET fail_streak=0, last_seen=? WHERE serial=?", (now, serial))
        else:
            conn.execute("UPDATE devices SET fail_streak=fail_streak+1 WHERE serial=?", (serial,))
            row = conn.execute("SELECT fail_streak, state FROM devices WHERE serial=?", (serial,)).fetchone()
            if row and row["fail_streak"] >= threshold and row["state"] != "quarantined":
                conn.execute(
                    "UPDATE leases SET released=?, reason='quarantined' WHERE serial=? AND released IS NULL",
                    (now, serial),
                )
                conn.execute("UPDATE devices SET state='quarantined' WHERE serial=?", (serial,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_host(conn, host, ok, detail, now=None):
    now = time.time() if now is None else now
    conn.execute("INSERT INTO health(ts, subject, kind, ok, detail) VALUES(?,?,?,?,?)", (now, host, "host", int(ok), detail))
    conn.execute("UPDATE hosts SET status=? WHERE name=?", ("up" if ok else "degraded", host))


def acquire(conn, owner, adapter, model=None, tag=None, ttl=3600, now=None):
    """Lease a free device. Each candidate is probed first; a bad one is skipped and counted.

    The claim is one conditional UPDATE, so two callers can never get the same device.
    Returns a dict, or None when nothing healthy is free.
    """
    now = time.time() if now is None else now
    tag_pat = f"%,{tag},%" if tag else None
    candidates = conn.execute(
        "SELECT d.serial FROM devices d JOIN hosts h ON h.name=d.host "
        "WHERE d.state='free' AND h.status='up' "
        "AND (? IS NULL OR d.model=?) AND (? IS NULL OR (',' || d.tags || ',') LIKE ?) "
        "ORDER BY d.fail_streak, d.serial",
        (model, model, tag, tag_pat),
    ).fetchall()
    for row in candidates:
        serial = row["serial"]
        ok, detail = adapter.probe(serial)
        record_probe(conn, serial, ok, detail, now)
        if not ok:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            claimed = conn.execute("UPDATE devices SET state='leased' WHERE serial=? AND state='free'", (serial,))
            if claimed.rowcount != 1:
                conn.execute("ROLLBACK")
                continue
            cur = conn.execute(
                "INSERT INTO leases(serial, owner, started, expires) VALUES(?,?,?,?)", (serial, owner, now, now + ttl)
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"id": cur.lastrowid, "serial": serial, "owner": owner, "expires": now + ttl}
    return None


def release(conn, lease_id, now=None, reason="released"):
    now = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT serial FROM leases WHERE id=? AND released IS NULL", (lease_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return False
        conn.execute("UPDATE leases SET released=?, reason=? WHERE id=?", (now, reason, lease_id))
        conn.execute("UPDATE devices SET state='free' WHERE serial=? AND state='leased'", (row["serial"],))
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def reap(conn, now=None):
    """End every lease past its expiry. A crashed job must not hold a device forever."""
    now = time.time() if now is None else now
    expired = conn.execute("SELECT id, serial, owner FROM leases WHERE released IS NULL AND expires<=?", (now,)).fetchall()
    out = []
    for row in expired:
        if release(conn, row["id"], now, "expired"):
            out.append({"id": row["id"], "serial": row["serial"], "owner": row["owner"]})
    return out


def unquarantine(conn, serial):
    """A human puts a repaired device back. Probes never do this on their own."""
    cur = conn.execute("UPDATE devices SET state='free', fail_streak=0 WHERE serial=? AND state='quarantined'", (serial,))
    return cur.rowcount == 1
