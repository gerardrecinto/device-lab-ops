"""A small REST API so test jobs can lease and release devices. Standard library only."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, pool, report

MAX_BODY = 64 * 1024


def make_server(db_path, adapter, host="127.0.0.1", port=8080, token=None):
    token = token if token is not None else os.environ.get("DEVICELAB_TOKEN")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self):
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                self._send(401, {"error": "missing or wrong bearer token"})
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("body too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            conn = db.connect(db_path)
            try:
                if self.path == "/healthz":
                    return self._send(200, {"ok": True})
                if self.path == "/metrics":
                    return self._send(200, report.metrics_text(conn), "text/plain; version=0.0.4")
                if self.path.startswith("/devices"):
                    m = re.search(r"state=(free|leased|quarantined)", self.path)
                    sql = "SELECT serial, host, model, tags, state, fail_streak FROM devices"
                    rows = conn.execute(
                        sql + (" WHERE state=?" if m else "") + " ORDER BY serial", (m.group(1),) if m else ()
                    )
                    return self._send(200, [dict(r) for r in rows])
                if self.path == "/status":
                    return self._send(200, report.status(conn))
                self._send(404, {"error": "not found"})
            finally:
                conn.close()

        def do_POST(self):
            if not self._authed():
                return
            conn = db.connect(db_path)
            try:
                if self.path == "/leases":
                    try:
                        req = self._body()
                        owner = str(req["owner"])
                        ttl = int(req.get("ttl", 3600))
                    except (ValueError, KeyError, TypeError):
                        return self._send(400, {"error": "need JSON with owner and optional model, tag, ttl"})
                    if not 1 <= ttl <= 86400:
                        return self._send(400, {"error": "ttl must be 1 to 86400 seconds"})
                    lease = pool.acquire(conn, owner, adapter, req.get("model"), req.get("tag"), ttl)
                    if lease is None:
                        return self._send(409, {"error": "no healthy free device matches"})
                    return self._send(201, lease)
                if self.path == "/reap":
                    return self._send(200, pool.reap(conn))
                self._send(404, {"error": "not found"})
            finally:
                conn.close()

        def do_DELETE(self):
            if not self._authed():
                return
            m = re.fullmatch(r"/leases/(\d+)", self.path)
            if not m:
                return self._send(404, {"error": "not found"})
            conn = db.connect(db_path)
            try:
                if pool.release(conn, int(m.group(1))):
                    return self._send(200, {"released": int(m.group(1))})
                self._send(404, {"error": "no active lease with that id"})
            finally:
                conn.close()

    return ThreadingHTTPServer((host, port), Handler)
