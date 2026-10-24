import json
import threading
import urllib.error
import urllib.request

import pytest

from agentbrief.cli import START, main, upsert_section
from agentbrief.server import ThreadingHTTPServer, make_handler

from conftest import write


def test_upsert_section_is_idempotent_and_preserves_user_text():
    section = f"{START}\nv1\n<!-- agentbrief:end -->"
    once = upsert_section("# My rules\n\nBe nice.\n", section)
    assert once.startswith("# My rules") and "v1" in once
    twice = upsert_section(once, section.replace("v1", "v2"))
    assert "v2" in twice and "v1" not in twice and twice.count(START) == 1


def test_init_writes_agents_md_and_links_claude_md(tmp_path):
    write(tmp_path, "CLAUDE.md", "# Project rules\n")
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert "Feature manifests" in (tmp_path / "AGENTS.md").read_text()
    assert "@AGENTS.md" in (tmp_path / "CLAUDE.md").read_text()
    assert (tmp_path / ".agentbrief/features").is_dir()


def test_check_and_test_exit_codes(project, capsys):
    assert main(["--root", str(project), "check"]) == 0
    assert main(["--root", str(project), "test", "addition"]) == 0
    write(project, ".agentbrief/features/broken.yaml", """
        id: broken
        title: Broken
        summary: s
        tests:
          - path: tests/test_calc.py
            symbol: TestCalculator.test_broken
        code:
          - path: calc.py
            symbol: gone
        """)
    assert main(["--root", str(project), "check"]) == 1
    assert "symbol 'gone' not found" in capsys.readouterr().out
    assert main(["--root", str(project), "test", "broken"]) == 1


@pytest.fixture
def server(project):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project, None, "secret"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def call(url, body=None, token=None, host=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode())
    if token:
        req.add_header("X-Agentbrief-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()) if "json" in r.headers["Content-Type"] else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_serves_features_and_guards_writes(server):
    status, data = call(server + "/api/overview")
    assert status == 200 and data["features"][0]["id"] == "addition"
    status, detail = call(server + "/api/features/addition")
    assert detail["code"][0]["symbol"] == "add"
    assert detail["questions"][0]["answer"].startswith("Yes")

    review = {"feature_id": "addition", "status": "approved", "fingerprint": detail["fingerprint"],
              "checked_code": [0], "answers": [False]}
    assert call(server + "/api/review", review)[0] == 403  # no token
    assert call(server + "/api/review", review, token="secret", host="evil.example")[0] == 403
    assert call(server + "/api/review", dict(review, fingerprint="old"), token="secret")[0] == 409
    assert call(server + "/api/review", review, token="secret")[0] == 200
    after = call(server + "/api/features/addition")[1]
    assert after["review_status"] == "approved" and after["review"]["quiz"] == {"correct": 0, "total": 1}


def test_server_blocks_approval_until_code_checked_and_questions_answered(server):
    fp = call(server + "/api/features/addition")[1]["fingerprint"]
    base = {"feature_id": "addition", "fingerprint": fp}
    status, body = call(server + "/api/review", dict(base, status="approved", checked_code=[0]), token="secret")
    assert status == 400 and "answer every question" in body["error"]
    # Requesting changes is never gated: you may spot a problem before finishing the quiz.
    assert call(server + "/api/review", dict(base, status="changes-requested"), token="secret")[0] == 200


def test_server_runs_feature_tests(server):
    status, run = call(server + "/api/run-tests", {"feature_id": "addition"}, token="secret")
    assert status == 200 and run["exit_code"] == 0
    assert call(server + "/api/features/addition")[1]["tests_outcome"] == "passed"
