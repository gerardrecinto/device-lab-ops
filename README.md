# device-lab-ops

A device farm pool for an ML hardware lab. Test jobs lease a device over a REST API. The pool probes each device before handing it out, ends the lease if the job crashes, quarantines a device that keeps failing, and stops using a host whose NFS mount hangs. Python standard library only.

[![CI](https://github.com/gerardrecinto/device-lab-ops/actions/workflows/ci.yml/badge.svg)](https://github.com/gerardrecinto/device-lab-ops/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/gerardrecinto/device-lab-ops)](LICENSE)

**[Live page: real output and a capacity planner](https://gerardrecinto.github.io/device-lab-ops/)**

## Run it

Python 3.10 or newer. No other dependencies.

```bash
git clone https://github.com/gerardrecinto/device-lab-ops
cd device-lab-ops
pip install -e .
devicelab demo
```

`demo` runs a scripted scenario on a throwaway database. The last lines:

```
5. Least healthy
   device SN-0003: 3/3 probes failed
6. Next hardware cycle: 600 jobs a day, 25 minutes each, 2x peak, 70% target use, 4 devices per host
   30 working devices, 32 with spares, 9 hosts
   buy 24 (8 on hand)
```

Use it on the sample inventory (8 simulated devices on 2 hosts):

```bash
devicelab init                        # loads examples/inventory.json into devicelab.db
devicelab lease job-1 --model gen1    # probes, then prints the lease as JSON
devicelab status
devicelab probe --events hec.log      # probe everything, write Splunk HEC lines
devicelab report --hours 24           # utilization and least healthy
devicelab serve                       # REST API on 127.0.0.1:8080
```

Or in a container: `docker build -t devicelab . && docker run -p 8080:8080 devicelab`.

## REST API

| Call | What it does |
|---|---|
| `GET /healthz`, `/status`, `/metrics` | liveness, devices per host, Prometheus text |
| `GET /devices?state=free` | list devices, optionally by state |
| `POST /leases` `{"owner":"job-1","model":"gen1","tag":"int8","ttl":900}` | lease a healthy device; 409 if none |
| `DELETE /leases/<id>` | release |
| `POST /reap` | end expired leases |

Set `DEVICELAB_TOKEN` and writes need `Authorization: Bearer <token>`. The server binds to 127.0.0.1 unless you pass `--bind`.

## Design choices

- **Leases with expiry, not permanent assignment.** A crashed job must not hold a device forever. Cost: something has to run `reap` (cron, or `POST /reap`). A one-of-a-kind board that is never shared would be better with static assignment.
- **One active lease per device is a database rule** (partial unique index), and the claim is a single conditional `UPDATE`. Two callers cannot get the same device even if the code has a bug. Test: 12 threads race for 4 devices, exactly 4 win.
- **Probe before lease, quarantine after three misses in a row.** A passing probe never un-quarantines; a person does, with `devicelab unquarantine`. Cost: a device with a flaky cable stays out until someone looks. Flip to auto-recovery only if you have a reliable power-cycle path.
- **NFS check runs in a child process with a timeout.** A stale NFS mount makes `stat` block forever, so checking in-process would hang the health checker itself.
- **SQLite, not a server database.** One file, no setup, enough for one lab. For several sites, the same schema moves to PostgreSQL.

## What is verified

- 35 tests run in CI on Python 3.10, 3.12 and 3.13, plus a container job that leases a device through the running image.
- The simulated adapter is what the tests and demo use. The shell adapter (`examples/inventory.shell.json`, for example `adb -s {serial} get-state`) is tested with stand-in commands.
- NFS: the stale-mount check is tested with a command that hangs.
- Splunk: events are written in HEC format and the direct POST is tested against a local server.

## Layout

```
src/devicelab/   pool.py (leases, quarantine), hostcheck.py, adapters.py, events.py, report.py, capacity.py, api.py, cli.py
examples/        sample inventory, shell-adapter inventory
docs/            GitHub Pages site (built by scripts/build_page.py from real demo output)
tests/           pool, checks, API, CLI, page parity
```

MIT licensed.
