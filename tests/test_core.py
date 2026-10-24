import subprocess

from agentbrief import core
from agentbrief.models import load_features

from conftest import write


def test_run_tests_records_pass_fail_and_missing(project):
    run = core.run_tests(project, [
        "tests/test_calc.py::test_add",
        "tests/test_calc.py::TestCalculator::test_broken",
        "tests/test_calc.py::test_does_not_exist",
    ])
    res = run["results"]
    # Parametrized cases are reported individually but match the function reference.
    cases = core.match_results("tests/test_calc.py::test_add", res)
    assert len(cases) == 2 and all(c["outcome"] == "passed" for c in cases)
    broken = res["tests/test_calc.py::TestCalculator::test_broken"]
    assert broken["outcome"] == "failed" and "assert 4 == 5" in broken["longrepr"]
    assert res["tests/test_calc.py::test_does_not_exist"]["outcome"] == "missing"
    # Results persist for the UI.
    assert "tests/test_calc.py::test_add[1-2]" in core.load_results(project)


def test_aggregate_prefers_the_worst_outcome():
    assert core.aggregate([]) == "not-run"
    assert core.aggregate(["passed", "skipped"]) == "passed"
    assert core.aggregate(["skipped"]) == "skipped"
    assert core.aggregate(["passed", "not-run"]) == "not-run"
    assert core.aggregate(["passed", "missing", "error"]) == "failed"


def test_review_goes_stale_when_reviewed_code_changes(project):
    (feature,), _ = load_features(project)
    view = core.feature_view(project, feature, {}, {})
    core.save_review(project, "addition", "approved", "lgtm", view["fingerprint"])
    assert core.feature_view(project, feature, {}, core.load_reviews(project))["review_status"] == "approved"

    calc = project / "calc.py"
    calc.write_text(calc.read_text().replace("return a + b", "return a + b + 0"))
    assert core.feature_view(project, feature, {}, core.load_reviews(project))["review_status"] == "stale"


def test_review_ignores_edits_outside_referenced_symbols(project):
    (feature,), _ = load_features(project)
    fp = core.feature_view(project, feature, {}, {})["fingerprint"]
    core.save_review(project, "addition", "approved", "", fp)
    calc = project / "calc.py"
    calc.write_text(calc.read_text().replace("return x * 2", "return x + x"))
    assert core.feature_view(project, feature, {}, core.load_reviews(project))["review_status"] == "approved"


def test_done_feature_without_tests_or_questions_is_a_problem(project):
    write(project, ".agentbrief/features/untested.yaml", "id: untested\ntitle: T\nsummary: s\n")
    write(project, ".agentbrief/features/planned.yaml", "id: planned\ntitle: T\nsummary: s\nstatus: planned\n")
    views = {v["id"]: v for v in core.overview(project, None)["features"]}
    assert "marked done but lists no tests" in views["untested"]["problems"]
    assert "marked done but has no review questions" in views["untested"]["problems"]
    assert views["planned"]["problems"] == [] and views["addition"]["problems"] == []


def test_approval_gate_requires_all_code_checked_and_all_questions_answered(project):
    (feature,), _ = load_features(project)  # 1 code block, 1 question
    assert core.approval_gate(feature, [0], [True]) == {"correct": 1, "total": 1}
    assert core.approval_gate(feature, [0], [False]) == {"correct": 0, "total": 1}
    assert core.approval_gate(feature, [], [True]) is None        # code not checked
    assert core.approval_gate(feature, [0], []) is None           # question unanswered
    assert core.approval_gate(feature, [0], [None]) is None       # revealed but not graded
    assert core.approval_gate(feature, [0, 1], [True]) is None    # bogus index


def test_overview_lists_changed_files_no_feature_covers(project):
    git = lambda *a: subprocess.run(["git", *a], cwd=project, check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    write(project, "stray.py", "x = 1\n")
    o = core.overview(project, None)
    assert "stray.py" in o["uncovered_files"]
    assert "calc.py" not in o["uncovered_files"]  # referenced by the addition feature
    assert not any(p.startswith(".agentbrief/") for p in o["uncovered_files"])
