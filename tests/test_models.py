import pytest

from agentbrief.models import load_features, parse_feature

from conftest import write


def test_parse_minimal_feature_defaults_to_done():
    f = parse_feature({"id": "x", "title": "X", "summary": "does x"}, "m.yaml")
    assert f.status == "done" and f.code == [] and f.tests == []


@pytest.mark.parametrize("data,msg", [
    ({"title": "X", "summary": "s"}, "missing required"),
    ({"id": "Bad_Id", "title": "X", "summary": "s"}, "kebab-case"),
    ({"id": "x", "title": "X", "summary": "s", "status": "shipped"}, "status"),
    ({"id": "x", "title": "X", "summary": "s", "code": [{"symbol": "f"}]}, "path"),
    ({"id": "x", "title": "X", "summary": "s", "code": [{"path": "a.py", "lines": "9-3"}]}, "line range"),
    ([1, 2], "mapping"),
    ({"id": "x", "title": "X", "summary": "s", "questions": [{"question": "why?"}]}, "answer"),
])
def test_parse_rejects_invalid_manifests(data, msg):
    with pytest.raises(ValueError, match=msg):
        parse_feature(data, "m.yaml")


def test_refs_accept_shorthand_and_line_ranges():
    f = parse_feature({
        "id": "x", "title": "X", "summary": "s",
        "code": [{"path": "a.ts", "lines": "4-9"}, {"path": "b.py", "lines": 7}],
        "tests": ["tests/test_a.py::TestA::test_b", "tests/test_c.py"],
    }, "m.yaml")
    assert f.code[0].lines == (4, 9) and f.code[1].lines == (7, 7)
    assert f.tests[0].symbol == "TestA.test_b"
    assert f.tests[0].nodeid == "tests/test_a.py::TestA::test_b"
    assert f.tests[1].nodeid == "tests/test_c.py"


def test_questions_are_parsed_with_optional_hint():
    f = parse_feature({"id": "x", "title": "X", "summary": "s", "questions": [
        {"question": " Q1? ", "answer": "A1", "about": "a.py::f"}, {"question": "Q2?", "answer": "A2"}]}, "m.yaml")
    assert [(q.question, q.answer, q.about) for q in f.questions] == [("Q1?", "A1", "a.py::f"), ("Q2?", "A2", None)]


def test_load_reports_bad_files_without_dropping_good_ones(project):
    write(project, ".agentbrief/features/broken.yaml", "id: [unclosed\n")
    write(project, ".agentbrief/features/renamed.yaml", "id: other\ntitle: T\nsummary: s\n")
    write(project, ".agentbrief/features/dupe.yml", "id: addition\ntitle: T\nsummary: s\n")
    features, errors = load_features(project)
    assert [f.id for f in features] == ["addition"]
    assert len(errors) == 3
    assert any("must match the filename" in e for e in errors)
