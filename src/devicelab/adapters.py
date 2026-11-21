"""How the lab talks to a device. Swap the adapter, keep the pool logic.

SimAdapter is for tests and the demo. ShellAdapter runs a command you give it, for example
`adb -s {serial} get-state`, and treats exit code 0 as healthy. It has not been run against
physical hardware in this repo.
"""

import shlex
import subprocess


class SimAdapter:
    """Deterministic fake devices. `fail` maps serial -> number of probes that fail before it recovers."""

    def __init__(self, fail=None):
        self.fail = dict(fail or {})
        self.reboots = []

    def probe(self, serial):
        left = self.fail.get(serial, 0)
        if left > 0:
            self.fail[serial] = left - 1
            return False, "no response from device"
        return True, "ok"

    def reboot(self, serial):
        self.reboots.append(serial)
        return True, "reboot requested"


class ShellAdapter:
    def __init__(self, probe_cmd, reboot_cmd=None, timeout=10):
        self.probe_cmd = probe_cmd
        self.reboot_cmd = reboot_cmd
        self.timeout = timeout

    def _run(self, template, serial):
        argv = [part.replace("{serial}", serial) for part in shlex.split(template)]
        try:
            res = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return False, f"timed out after {self.timeout}s"
        except OSError as exc:
            return False, f"cannot run {argv[0]}: {exc.strerror}"
        text = (res.stdout or res.stderr).strip().splitlines()
        return res.returncode == 0, (text[0] if text else f"exit {res.returncode}")

    def probe(self, serial):
        return self._run(self.probe_cmd, serial)

    def reboot(self, serial):
        if not self.reboot_cmd:
            return False, "no reboot command configured"
        return self._run(self.reboot_cmd, serial)


def from_config(cfg):
    cfg = cfg or {"type": "sim"}
    kind = cfg.get("type", "sim")
    if kind == "sim":
        return SimAdapter(cfg.get("fail"))
    if kind == "shell":
        return ShellAdapter(cfg["probe"], cfg.get("reboot"), cfg.get("timeout", 10))
    raise ValueError(f"unknown adapter type: {kind}")
