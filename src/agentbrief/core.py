"""Everything the CLI and the web UI share: tests, reviews, git and feature views."""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import textwrap
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from .extract import extract
from .models import BRIEF_DIR, CodeRef, Feature, Move, load_features

CACHE_DIR = ".cache"
RESULTS_FILE = "test-results.json"
REVIEWS_FILE = "reviews.json"
CONFIG_FILE = "config.yaml"
REVIEW_STATUSES = ("approved", "changes-requested")


def _sup(root: Path) -> Path:
    return root / BRIEF_DIR


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_config(root: Path) -> Dict[str, Any]:
    path = _sup(root) / CONFIG_FILE
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# --------------------------------------------------------------------- tests

def load_results(root: Path) -> Dict[str, Any]:
    return _read_json(_sup(root) / CACHE_DIR / RESULTS_FILE)


def match_results(nodeid: str, results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Results for a reference; a function covers its parametrized cases, a file covers its tests."""
    return [
        dict(r, nodeid=k) for k, r in results.items()
        if k == nodeid or k.startswith(nodeid + "[") or k.startswith(nodeid + "::")
    ]


def aggregate(outcomes: Iterable[str]) -> str:
    outcomes = list(outcomes)
    if not outcomes:
        return "not-run"
    if "error" in outcomes or "failed" in outcomes:
        return "failed"
    if "missing" in outcomes or "not-run" in outcomes:
        return "missing" if "missing" in outcomes else "not-run"
    if all(o == "skipped" for o in outcomes):
        return "skipped"
    return "passed"


def _pytest(root: Path, extra: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    config = load_config(root)
    command = config.get("test_command") or [sys.executable, "-m", "pytest"]
    if isinstance(command, str):
        command = command.split()
    args = list(command) + ["-p", "agentbrief.pytest_plugin", "--rootdir", str(root)]
    args += list(config.get("pytest_args") or []) + extra
    return subprocess.run(args, cwd=root, env=env, capture_output=True, text=True)


def _existing(root: Path, nodeids: List[str]) -> List[str]:
    """Subset of node ids pytest can actually collect."""
    files = sorted({n.split("::")[0] for n in nodeids if (root / n.split("::")[0]).exists()})
    if not files:
        return []
    out = _pytest(root, ["--collect-only", "-q", *files]).stdout
    collected = [line.strip() for line in out.splitlines() if "::" in line]
    known = dict.fromkeys(collected, {})
    return [n for n in nodeids if ("::" not in n and n in files) or match_results(n, known)]


def run_tests(root: Path, nodeids: List[str]) -> Dict[str, Any]:
    """Run pytest on the given node ids (all tests if empty) and merge into the cache."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "results.json"
        env = dict(os.environ, AGENTBRIEF_RESULTS=str(out))
        started = time.time()
        proc = _pytest(root, ["-q", *nodeids], env)
        if proc.returncode == 4 and nodeids:
            # pytest aborts everything if a single node id doesn't exist; rerun the ones that do.
            runnable = _existing(root, nodeids)
            if runnable:
                proc = _pytest(root, ["-q", *runnable], env)
        fresh = _read_json(out)

    ran_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    for r in fresh.values():
        r["ran_at"] = ran_at
    # A requested node pytest never reported (typo, deleted test) is "missing", not silently passing.
    for nid in nodeids:
        if not match_results(nid, fresh):
            fresh[nid] = {"outcome": "missing", "duration": 0.0, "ran_at": ran_at,
                          "longrepr": "pytest did not report this test. Does it exist?"}

    cache_path = _sup(root) / CACHE_DIR / RESULTS_FILE
    cache = _read_json(cache_path)
    for nid in nodeids:  # drop stale entries (e.g. removed parametrizations) for what we re-ran
        for k in [k for k in cache if k == nid or k.startswith(nid + "[") or k.startswith(nid + "::")]:
            del cache[k]
    if not nodeids:
        cache = {}
    cache.update(fresh)
    _write_json(cache_path, cache)
    return {
        "exit_code": proc.returncode,
        "duration": round(time.time() - started, 2),
        "output": (proc.stdout + proc.stderr)[-20000:],
        "results": fresh,
    }


# ------------------------------------------------------------------- reviews

def load_reviews(root: Path) -> Dict[str, Any]:
    return _read_json(_sup(root) / REVIEWS_FILE)


def save_review(root: Path, feature_id: str, status: Optional[str], note: str, fingerprint: str,
                quiz: Optional[Dict[str, int]] = None) -> None:
    reviews = load_reviews(root)
    if status is None:
        reviews.pop(feature_id, None)
    else:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"review status must be one of {REVIEW_STATUSES}")
        reviews[feature_id] = {
            "status": status, "note": note, "fingerprint": fingerprint,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if quiz is not None:
            reviews[feature_id]["quiz"] = quiz
    _write_json(_sup(root) / REVIEWS_FILE, reviews)


def fingerprint(snippets: List[Dict[str, Any]]) -> str:
    """Hash of everything a reviewer looked at; if it changes, the review is stale."""
    h = hashlib.sha256()
    for s in snippets:
        h.update(f"{s['path']}\0{s['symbol']}\0{s['source']}\0".encode())
    return h.hexdigest()[:16]


# ----------------------------------------------------------------------- git

def _git(root: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def changed_files(root: Path, base: Optional[str]) -> Optional[List[str]]:
    """Files changed vs ``base`` (or HEAD) plus untracked files; None outside git."""
    diff = _git(root, "diff", "--name-only", base or "HEAD")
    if diff is None:
        diff = _git(root, "diff", "--name-only")  # repo without commits yet
        if diff is None:
            return None
    untracked = _git(root, "ls-files", "--others", "--exclude-standard") or ""
    return sorted({p for p in (diff + untracked).splitlines() if p})


def file_diff(root: Path, path: str, base: Optional[str]) -> str:
    out = _git(root, "diff", base or "HEAD", "--", path)
    if out:
        return out
    if _git(root, "ls-files", "--error-unmatch", "--", path) is None and (root / path).is_file():
        return "(new file, not tracked by git yet)"
    return ""


# ------------------------------------------------------------------- views

def _test_view(ref: CodeRef, root: Path, results: Dict[str, Any]) -> Dict[str, Any]:
    view = extract(root, ref)
    matched = match_results(ref.nodeid, results)
    view.update(
        nodeid=ref.nodeid,
        outcome=aggregate(r["outcome"] for r in matched),
        runs=matched,
        ran_at=max((r.get("ran_at", "") for r in matched), default=None),
    )
    return view


def _short_name(symbol: Optional[str]) -> str:
    return (symbol or "").rsplit(".", 1)[-1]


def move_view(root: Path, move: Move, base: Optional[str]) -> Dict[str, Any]:
    """Old code (from git at ``base``) next to new code (on disk), classified for the reviewer."""
    before = extract(root, move.before, base or "HEAD") if move.before else None
    after = extract(root, move.after) if move.after else None
    if before is None:
        kind = "new"
    elif after is None:
        kind = "removed"
    elif before["path"] != after["path"]:
        kind = "moved"
    elif before["symbol"] != after["symbol"]:
        kind = "renamed"
    else:
        kind = "edited"

    body, diff = None, ""
    if before and after and not before["error"] and not after["error"]:
        old, new = textwrap.dedent(before["source"]), textwrap.dedent(after["source"])
        old_name, new_name = _short_name(before["symbol"]), _short_name(after["symbol"])
        if old_name and new_name and old_name != new_name:
            # A rename alone shouldn't count as a body change.
            old = re.sub(rf"\b{re.escape(old_name)}\b", new_name, old)
        body = "unchanged" if old.strip() == new.strip() else "changed"
        if body == "changed":
            diff = "\n".join(difflib.unified_diff(
                old.splitlines(), new.splitlines(), lineterm="", n=3,
                fromfile=f"before: {before['path']}", tofile=f"after: {after['path']}"))
    return {"before": before, "after": after, "note": move.note, "kind": kind, "body": body, "diff": diff}


def feature_view(root: Path, feature: Feature, results: Dict[str, Any],
                 reviews: Dict[str, Any], detail: bool = False, base: Optional[str] = None) -> Dict[str, Any]:
    code = [extract(root, r) for r in feature.code]
    tests = [_test_view(r, root, results) for r in feature.tests]
    moves = [move_view(root, m, feature.base or base) for m in feature.moves]
    # Only the "after" side counts: the old code is history and must not make a review stale.
    fp = fingerprint(code + tests + [m["after"] for m in moves if m["after"]])
    review = reviews.get(feature.id)
    review_status = "unreviewed"
    if review:
        review_status = review["status"] if review.get("fingerprint") == fp else "stale"
    problems = [f"{s['path']}: {s['error']}" for s in code + tests if s["error"]]
    problems += [f"{m['after']['path']}: {m['after']['error']}" for m in moves if m["after"] and m["after"]["error"]]
    if feature.kind == "refactor" and not feature.moves:
        problems.append("refactor lists no moves")
    if feature.status == "done" and not feature.tests:
        problems.append("marked done but lists no tests")
    if feature.status == "done" and not feature.questions:
        problems.append("marked done but has no review questions")
    view: Dict[str, Any] = {
        "id": feature.id, "title": feature.title, "summary": feature.summary,
        "status": feature.status, "manifest": feature.manifest, "kind": feature.kind,
        "tests_outcome": aggregate(t["outcome"] for t in tests) if tests else "no-tests",
        "review_status": review_status, "review": review, "fingerprint": fp,
        "problems": problems,
        "files": sorted({r.path for r in feature.code + feature.tests}
                        | {r.path for m in feature.moves for r in (m.before, m.after) if r}),
        "code_count": len(code), "move_count": len(moves), "question_count": len(feature.questions),
    }
    if detail:
        view.update(details=feature.details, code=code, tests=tests, moves=moves,
                    base=feature.base or base or "HEAD",
                    questions=[{"question": q.question, "answer": q.answer, "about": q.about}
                               for q in feature.questions])
    return view


def overview(root: Path, base: Optional[str]) -> Dict[str, Any]:
    features, errors = load_features(root)
    results, reviews = load_results(root), load_reviews(root)
    views = [feature_view(root, f, results, reviews, base=base) for f in features]
    covered = {p for v in views for p in v["files"]}
    changed = changed_files(root, base)
    uncovered = None
    if changed is not None:
        ignore = [BRIEF_DIR + "/*", *(load_config(root).get("uncovered_ignore") or [])]
        uncovered = [p for p in changed
                     if p not in covered and not any(fnmatch.fnmatch(p, pat) for pat in ignore)]
    return {
        "root": str(root), "base": base or "HEAD", "features": views,
        "manifest_errors": errors, "changed_files": changed, "uncovered_files": uncovered,
    }


def approval_gate(feature: Feature, checked_code: Any, answers: Any) -> Optional[Dict[str, int]]:
    """Quiz score if every code block and move was checked and every question answered, else None.

    Checkable items are numbered code blocks first, then moves.
    """
    reviewable = len(feature.code) + len(feature.moves)
    if not isinstance(checked_code, list) or set(checked_code) != set(range(reviewable)):
        return None
    if not isinstance(answers, list) or len(answers) != len(feature.questions):
        return None
    if not all(isinstance(a, bool) for a in answers):
        return None
    return {"correct": sum(answers), "total": len(answers)}


def find_feature(root: Path, feature_id: str) -> Optional[Feature]:
    features, _ = load_features(root)
    return next((f for f in features if f.id == feature_id), None)
