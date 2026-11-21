import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from devicelab import capacity

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = [
    dict(
        jobs_per_day=600,
        job_minutes=25,
        target_util=0.7,
        peak_factor=2.0,
        spare_pct=5.0,
        devices_per_host=4,
        spare_hosts=1,
        existing_devices=8,
    ),
    dict(
        jobs_per_day=1000,
        job_minutes=14.4,
        target_util=1.0,
        peak_factor=1.0,
        spare_pct=0.0,
        devices_per_host=3,
        spare_hosts=0,
        existing_devices=0,
    ),
    dict(
        jobs_per_day=0,
        job_minutes=30,
        target_util=0.5,
        peak_factor=1.0,
        spare_pct=10.0,
        devices_per_host=8,
        spare_hosts=2,
        existing_devices=3,
    ),
    dict(
        jobs_per_day=37,
        job_minutes=91,
        target_util=0.65,
        peak_factor=1.5,
        spare_pct=12.5,
        devices_per_host=6,
        spare_hosts=1,
        existing_devices=2,
    ),
]


def test_page_is_up_to_date_with_demo_output():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_page

    assert (ROOT / "docs" / "index.html").read_text() == build_page.render(), "run: python scripts/build_page.py"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_planner_matches_python():
    js_cases = [
        dict(
            jobsPerDay=c["jobs_per_day"],
            jobMinutes=c["job_minutes"],
            targetUtil=c["target_util"],
            peak=c["peak_factor"],
            sparePct=c["spare_pct"],
            devicesPerHost=c["devices_per_host"],
            spareHosts=c["spare_hosts"],
            existing=c["existing_devices"],
        )
        for c in CASES
    ]
    script = f"const {{plan}}=require('./docs/planner.js'); console.log(JSON.stringify({json.dumps(js_cases)}.map(plan)))"
    out = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [capacity.plan(**c) for c in CASES]
