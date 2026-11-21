import http.server
import json
import os
import shlex
import sys
import threading
import time

import pytest

from devicelab import adapters, capacity, events, hostcheck, report


def test_disk_check_threshold(tmp_path):
    assert hostcheck.check_disk(str(tmp_path), 0.0)[0] is True
    assert hostcheck.check_disk(str(tmp_path), 100.0)[0] is False


def test_not_a_mount_fails(tmp_path):
    ok, detail = hostcheck.check_mount(str(tmp_path))
    assert not ok and "not a mount" in detail


def test_hung_mount_times_out_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    start = time.time()
    ok, detail = hostcheck.check_mount(
        "/mnt/x", timeout=0.5, stat_argv=[sys.executable, "-c", "import time; time.sleep(30)"]
    )
    assert not ok and "stale or hung" in detail
    assert time.time() - start < 5


def test_live_mount_answers(monkeypatch):
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    assert hostcheck.check_mount("/", timeout=5)[0] is True


def _py(code):
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def test_shell_adapter_uses_exit_code_and_serial():
    assert adapters.ShellAdapter(_py("import sys; sys.exit(0 if sys.argv[1] == 'X' else 1)") + " {serial}").probe("X")[0]
    assert not adapters.ShellAdapter(_py("import sys; sys.exit(0 if sys.argv[1] == 'X' else 1)") + " {serial}").probe("Y")[0]
    assert adapters.ShellAdapter("definitely-not-a-binary {serial}").probe("X")[0] is False
    ok, detail = adapters.ShellAdapter(_py("import sys; print('device'); sys.exit(3)")).probe("X")
    assert ok is False and detail == "device"


def test_shell_adapter_timeout():
    ok, detail = adapters.ShellAdapter(_py("import time; time.sleep(5)"), timeout=0.3).probe("X")
    assert not ok and "timed out" in detail


def test_from_config():
    assert isinstance(adapters.from_config(None), adapters.SimAdapter)
    with pytest.raises(ValueError):
        adapters.from_config({"type": "nope"})


def test_hec_shape_and_file_sink(tmp_path):
    ev = events.hec_event("h1", "health", {"ok": True}, 12.5)
    assert ev == {"time": 12.5, "host": "h1", "source": "devicelab", "sourcetype": "devicelab:health", "event": {"ok": True}}
    path = tmp_path / "e.log"
    events.to_file(str(path), [ev, ev])
    assert [json.loads(line) for line in path.read_text().splitlines()] == [ev, ev]


def test_hec_post_sends_token_and_body():
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers["Authorization"]
            seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ev = events.hec_event("h1", "health", {"ok": True}, 1.0)
    status = events.to_hec(f"http://127.0.0.1:{srv.server_port}/services/collector/event", "tok", [ev, ev])
    srv.shutdown()
    assert status == 200 and seen["auth"] == "Splunk tok" and seen["body"].count(b"\n") == 1


def test_capacity_known_case():
    res = capacity.plan(600, 25, 0.7, 2.0, 5.0, 4, 1, existing_devices=8)
    assert res == {"working_devices": 30, "devices": 32, "hosts": 9, "to_buy": 24}


def test_capacity_floor_and_validation():
    assert capacity.plan(0, 10)["devices"] == 0
    assert capacity.plan(10, 10, existing_devices=50)["to_buy"] == 0
    for bad in ({"target_util": 0}, {"spare_pct": 100}, {"devices_per_host": 0}, {"peak_factor": 0.5}):
        with pytest.raises(ValueError):
            capacity.plan(10, 10, **bad)


def test_utilization_clips_to_window(conn):
    conn.execute("INSERT INTO leases(serial, owner, started, expires, released) VALUES('A1','a',0,100,100)")
    rows = {r["model"]: r for r in report.utilization(conn, since=50, until=150)}
    assert rows["gen1"]["busy_pct"] == 50.0
    assert rows["gen2"]["busy_pct"] == 0.0


def test_utilization_counts_open_lease_to_window_end(conn):
    conn.execute("INSERT INTO leases(serial, owner, started, expires) VALUES('A2','a',0,9999)")
    rows = {r["model"]: r for r in report.utilization(conn, since=0, until=100)}
    assert rows["gen2"]["busy_pct"] == round(100.0 * 100 / (3 * 100), 1)


def test_flaky_lists_hosts_and_devices(conn):
    from devicelab import pool

    pool.record_probe(conn, "A1", False, "x", now=1.0)
    pool.record_probe(conn, "A1", True, "ok", now=2.0)
    pool.record_host(conn, "h2", False, "disk", now=3.0)
    top = report.flaky(conn)
    assert [(r["subject"], r["fail_pct"]) for r in top] == [("h2", 100.0), ("A1", 50.0)]
