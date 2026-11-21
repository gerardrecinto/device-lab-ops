"""Checks for the x86 hosts that drive the devices: disk space and NFS mounts that do not hang."""

import os
import shutil
import subprocess
import sys

_STAT = [sys.executable, "-c", "import os,sys; os.stat(sys.argv[1])"]


def check_disk(path, min_free_pct):
    usage = shutil.disk_usage(path)
    free_pct = 100.0 * usage.free / usage.total
    ok = free_pct >= min_free_pct
    return ok, f"{path} {free_pct:.1f}% free (min {min_free_pct}%)"


def check_mount(path, timeout=5, stat_argv=None):
    """A stale NFS mount makes stat() hang forever, so the stat runs in a child process with a timeout."""
    if not os.path.ismount(path):
        return False, f"{path} is not a mount point"
    argv = (stat_argv or _STAT) + ([path] if stat_argv is None else [])
    try:
        res = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{path} did not answer in {timeout}s (stale or hung)"
    if res.returncode != 0:
        return False, f"{path} stat failed"
    return True, f"{path} answers"


def run_checks(cfg):
    """cfg: {"disk_path": "/", "min_free_pct": 10, "mounts": ["/mnt/artifacts"]}. Returns [(name, ok, detail)]."""
    results = []
    if cfg.get("disk_path"):
        ok, detail = check_disk(cfg["disk_path"], cfg.get("min_free_pct", 10))
        results.append(("disk", ok, detail))
    for mount in cfg.get("mounts", []):
        ok, detail = check_mount(mount, cfg.get("mount_timeout", 5))
        results.append((f"mount:{mount}", ok, detail))
    return results
