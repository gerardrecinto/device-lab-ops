"""Reads over the pool database. All plain SQL, so the same queries work in a Splunk DB Connect or a BI tool."""


def status(conn):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT h.name AS host, h.status AS host_status, "
            "SUM(d.state='free') AS free, SUM(d.state='leased') AS leased, SUM(d.state='quarantined') AS quarantined "
            "FROM hosts h LEFT JOIN devices d ON d.host=h.name GROUP BY h.name ORDER BY h.name"
        )
    ]


def utilization(conn, since, until):
    """Percent of device-time leased inside the window, per model."""
    rows = conn.execute(
        "SELECT d.model AS model, COUNT(DISTINCT d.serial) AS devices, "
        "COALESCE(SUM(MAX(0, MIN(COALESCE(l.released, :until), :until) - MAX(l.started, :since))), 0) AS busy "
        "FROM devices d LEFT JOIN leases l ON l.serial=d.serial "
        "AND l.started < :until AND COALESCE(l.released, :until) > :since "
        "GROUP BY d.model ORDER BY d.model",
        {"since": since, "until": until},
    ).fetchall()
    span = until - since
    return [
        {"model": r["model"], "devices": r["devices"], "busy_pct": round(100.0 * r["busy"] / (r["devices"] * span), 1)}
        for r in rows
    ]


def flaky(conn, top=5):
    """Probe failure rate per subject. One bad host looks like many bad devices, so hosts are listed too."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT subject, kind, COUNT(*) AS probes, SUM(1-ok) AS failures, "
            "ROUND(100.0*SUM(1-ok)/COUNT(*), 1) AS fail_pct FROM health "
            "GROUP BY subject, kind HAVING failures > 0 ORDER BY fail_pct DESC, subject LIMIT ?",
            (top,),
        )
    ]


def metrics_text(conn):
    """Prometheus text format."""
    lines = ["# TYPE devicelab_devices gauge"]
    for state in ("free", "leased", "quarantined"):
        n = conn.execute("SELECT COUNT(*) FROM devices WHERE state=?", (state,)).fetchone()[0]
        lines.append(f'devicelab_devices{{state="{state}"}} {n}')
    lines.append("# TYPE devicelab_hosts_degraded gauge")
    lines.append(
        f"devicelab_hosts_degraded {conn.execute('SELECT COUNT(*) FROM hosts WHERE status!=?', ('up',)).fetchone()[0]}"
    )
    return "\n".join(lines) + "\n"
