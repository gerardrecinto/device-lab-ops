import json
import threading
import urllib.error
import urllib.request

import pytest
from conftest import INV

from devicelab import adapters, api, cli, db, pool


@pytest.fixture
def server(tmp_path):
    path = str(tmp_path / "api.db")
    c = db.connect(path)
    pool.load_inventory(c, INV)
    c.close()
    srv = api.make_server(path, adapters.SimAdapter(), port=0, token="secret")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def call(url, method="GET", body=None, token=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_health_devices_metrics_need_no_token(server):
    assert call(server + "/healthz")[0] == 200
    code, body = call(server + "/devices?state=free")
    assert code == 200 and len(json.loads(body)) == 4
    assert 'devicelab_devices{state="free"} 4' in call(server + "/metrics")[1]


def test_writes_need_the_token(server):
    assert call(server + "/leases", "POST", {"owner": "j"})[0] == 401
    assert call(server + "/leases", "POST", {"owner": "j"}, token="wrong")[0] == 401


def test_lease_lifecycle_over_http(server):
    code, body = call(server + "/leases", "POST", {"owner": "job-1", "model": "gen1"}, "secret")
    lease = json.loads(body)
    assert code == 201 and lease["serial"] == "A1"
    assert call(server + "/leases", "POST", {"owner": "job-2", "model": "gen1"}, "secret")[0] == 409
    assert call(server + f"/leases/{lease['id']}", "DELETE", token="secret")[0] == 200
    assert call(server + f"/leases/{lease['id']}", "DELETE", token="secret")[0] == 404
    assert call(server + "/leases", "POST", {"owner": "job-3", "model": "gen1"}, "secret")[0] == 201


def test_bad_requests(server):
    assert call(server + "/leases", "POST", {"model": "gen1"}, "secret")[0] == 400
    assert call(server + "/leases", "POST", {"owner": "j", "ttl": 0}, "secret")[0] == 400
    assert call(server + "/leases", "POST", {"owner": "j", "ttl": "x"}, "secret")[0] == 400
    assert call(server + "/nope")[0] == 404


def test_cli_end_to_end(tmp_path, capsys):
    db_path = str(tmp_path / "cli.db")
    inv = "examples/inventory.json"
    assert cli.main(["--db", db_path, "init", "--inventory", inv]) == 0
    assert cli.main(["--db", db_path, "lease", "job-1", "--inventory", inv, "--model", "gen1"]) == 0
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["serial"] == "SN-0001"
    ev = str(tmp_path / "hec.log")
    for _ in range(3):
        cli.main(["--db", db_path, "probe", "--inventory", inv, "--events", ev])
    text = capsys.readouterr().out
    assert "quarantined: SN-0007" in text
    assert any(json.loads(line)["event"].get("serial") == "SN-0007" for line in open(ev))
    assert cli.main(["--db", db_path, "unquarantine", "SN-0007"]) == 0
    assert cli.main(["--db", db_path, "unquarantine", "SN-0007"]) == 1
    assert cli.main(["--db", db_path, "release", "99"]) == 1


def test_cli_plan_and_missing_inventory(tmp_path, capsys):
    assert cli.main(["plan", "--jobs-per-day", "600", "--job-minutes", "25", "--peak", "2", "--existing", "8"]) == 0
    assert json.loads(capsys.readouterr().out)["to_buy"] == 24
    assert cli.main(["--db", str(tmp_path / "x.db"), "init", "--inventory", "nope.json"]) == 2
