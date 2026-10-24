"""pytest plugin that records per-node outcomes to a JSON file.

Loaded with ``-p agentbrief.pytest_plugin``; inert unless
``AGENTBRIEF_RESULTS`` points at an output file.
"""

import json
import os

ENV_VAR = "AGENTBRIEF_RESULTS"
_results = {}


def _record(nodeid, outcome, duration=0.0, longrepr=""):
    entry = _results.setdefault(nodeid, {"outcome": "passed", "duration": 0.0, "longrepr": ""})
    entry["duration"] += duration
    # Once a phase fails, later phases (e.g. teardown passing) must not hide it.
    if entry["outcome"] in ("failed", "error"):
        return
    if outcome != "passed":
        entry["outcome"] = outcome
        entry["longrepr"] = longrepr


def pytest_runtest_logreport(report):
    if not os.environ.get(ENV_VAR):
        return
    longrepr = str(report.longrepr) if report.longrepr else ""
    if report.failed:
        _record(report.nodeid, "failed" if report.when == "call" else "error", report.duration, longrepr)
    elif report.skipped:
        _record(report.nodeid, "skipped", report.duration, longrepr)
    else:
        _record(report.nodeid, "passed", report.duration)


def pytest_collectreport(report):
    if os.environ.get(ENV_VAR) and report.failed:
        _record(report.nodeid, "error", 0.0, str(report.longrepr))


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get(ENV_VAR)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(_results, fh)
