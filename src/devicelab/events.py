"""Splunk HTTP Event Collector events. Write them to a file a forwarder tails, or POST them directly."""

import json
import urllib.request


def hec_event(host, source, event, ts):
    return {"time": ts, "host": host, "source": "devicelab", "sourcetype": f"devicelab:{source}", "event": event}


def to_file(path, events):
    with open(path, "a") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")


def to_hec(url, token, events, timeout=5):
    """POST newline-delimited events to /services/collector/event. Returns the HTTP status."""
    body = "\n".join(json.dumps(ev) for ev in events).encode()
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Splunk {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
