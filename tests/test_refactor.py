import subprocess

import pytest

from agentbrief import core
from agentbrief.extract import extract
from agentbrief.models import CodeRef, load_features, parse_feature

from conftest import write


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def refactored(project):
    """`project` committed, then reorganized: one move, one rename, one edit, one removal, one new helper."""
    write(project, "shapes.py", """
        def area(w, h):
            return w * h


        def _perimeter(w, h):
            return 2 * (w + h)


        def describe(w, h):
            return f"{w}x{h}"


        def legacy():
            return None
        """)
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "before")
    base = git(project, "rev-parse", "HEAD").strip()

    write(project, "shapes.py", """
        def perimeter(w, h):
            return 2 * (w + h)


        def describe(w, h):
            return f"{w} by {h}"
        """)
    write(project, "geometry/area.py", """
        def area(w, h):
            return w * h


        def _check(w, h):
            assert w >= 0 and h >= 0
        """)
    write(project, ".agentbrief/features/reorganize-shapes.yaml", f"""
        id: reorganize-shapes
        kind: refactor
        title: Reorganize shapes
        base: {base}
        summary: Area gets its own module.
        moves:
          - from: shapes.py::area
            to: geometry/area.py::area
          - from: shapes.py::_perimeter
            to: shapes.py::perimeter
          - from: shapes.py::describe
            to: shapes.py::describe
          - from: shapes.py::legacy
          - to: geometry/area.py::_check
        tests: [tests/test_calc.py::test_add]
        questions:
          - question: Where is area now?
            answer: geometry/area.py
        """)
    return project, base


def view(root, base=None):
    features, errors = load_features(root)
    assert errors == []
    feature = next(f for f in features if f.id == "reorganize-shapes")
    return feature, core.feature_view(root, feature, {}, {}, detail=True, base=base)


def test_moves_are_classified_and_body_changes_detected(refactored):
    root, _ = refactored
    _, v = view(root)
    got = [(m["kind"], m["body"]) for m in v["moves"]]
    assert got == [
        ("moved", "unchanged"),
        ("renamed", "unchanged"),  # only the name changed
        ("edited", "changed"),
        ("removed", None),
        ("new", None),
    ]
    edited = v["moves"][2]
    assert '-    return f"{w}x{h}"' in edited["diff"] and '+    return f"{w} by {h}"' in edited["diff"]
    assert v["moves"][3]["before"]["source"].startswith("def legacy")  # removed code still viewable
    assert v["problems"] == [] and v["kind"] == "refactor"


def test_old_code_comes_from_base_even_after_the_refactor_is_committed(refactored):
    root, _ = refactored
    _, before_commit = view(root)
    git(root, "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "refactor")
    _, after_commit = view(root)
    assert after_commit["moves"][0]["body"] == "unchanged"
    # HEAD moved but the reviewed (new) code didn't, so an approval must not go stale.
    assert after_commit["fingerprint"] == before_commit["fingerprint"]


def test_missing_new_location_is_a_problem_but_missing_old_one_is_not(refactored):
    root, base = refactored
    manifest = root / ".agentbrief/features/reorganize-shapes.yaml"
    text = manifest.read_text()
    manifest.write_text(text.replace("to: geometry/area.py::area", "to: geometry/area.py::gone")
                            .replace("from: shapes.py::legacy", "from: shapes.py::never_existed"))
    _, v = view(root)
    assert v["problems"] == ["geometry/area.py: symbol 'gone' not found in geometry/area.py"]
    assert "never_existed" in v["moves"][3]["before"]["error"]


def test_moved_files_count_as_explained_changes(refactored):
    root, _ = refactored
    uncovered = core.overview(root, None)["uncovered_files"]
    assert "geometry/area.py" not in uncovered and "shapes.py" not in uncovered


def test_approval_requires_every_move_checked(refactored):
    root, _ = refactored
    feature, _ = view(root)
    assert core.approval_gate(feature, [0, 1, 2, 3], [True]) is None   # 5 moves, one unchecked
    assert core.approval_gate(feature, [0, 1, 2, 3, 4], [True]) == {"correct": 1, "total": 1}


def test_refactor_without_moves_and_bad_kind_are_rejected(project):
    write(project, ".agentbrief/features/empty-refactor.yaml",
          "id: empty-refactor\nkind: refactor\ntitle: T\nsummary: s\nstatus: planned\n")
    views = {v["id"]: v for v in core.overview(project, None)["features"]}
    assert "refactor lists no moves" in views["empty-refactor"]["problems"]
    with pytest.raises(ValueError, match="kind"):
        parse_feature({"id": "x", "title": "T", "summary": "s", "kind": "cleanup"}, "m.yaml")
    with pytest.raises(ValueError, match="'from', a 'to'"):
        parse_feature({"id": "x", "title": "T", "summary": "s", "moves": [{"note": "?"}]}, "m.yaml")


def test_git_ref_from_a_manifest_cannot_become_a_git_option(refactored):
    root, _ = refactored
    snippet = extract(root, CodeRef("shapes.py"), git_ref="--output=/tmp/pwned")
    assert "invalid git ref" in snippet["error"]
