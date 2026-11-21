"""How many devices and hosts a new hardware generation needs. The same formula is in docs/planner.js."""

import math


def plan(
    jobs_per_day,
    job_minutes,
    target_util=0.7,
    peak_factor=1.0,
    spare_pct=5.0,
    devices_per_host=4,
    spare_hosts=1,
    existing_devices=0,
):
    if not 0 < target_util <= 1:
        raise ValueError("target_util must be in (0, 1]")
    if not 0 <= spare_pct < 100:
        raise ValueError("spare_pct must be in [0, 100)")
    if devices_per_host < 1 or jobs_per_day < 0 or job_minutes < 0 or peak_factor < 1:
        raise ValueError("devices_per_host >= 1, jobs and minutes >= 0, peak_factor >= 1")
    busy_minutes = jobs_per_day * job_minutes * peak_factor
    working = math.ceil(busy_minutes / (1440 * target_util))
    devices = math.ceil(working / (1 - spare_pct / 100))
    hosts = math.ceil(devices / devices_per_host) + spare_hosts
    return {
        "working_devices": working,
        "devices": devices,
        "hosts": hosts,
        "to_buy": max(0, devices - existing_devices),
    }
