from agentbrief.extract import extract, find_python_symbol
from agentbrief.models import CodeRef

from conftest import write


def test_symbol_span_includes_decorators(project):
    s = extract(project, CodeRef("calc.py", symbol="add"))
    assert s["error"] is None
    assert s["source"].splitlines()[0] == "@functools.lru_cache()"
    assert s["source"].splitlines()[-1].strip() == "return a + b"


def test_method_lookup_by_dotted_name():
    src = "class A:\n    def f(self):\n        pass\n    def g(self):\n        return 1\n"
    assert find_python_symbol(src, "A.g") == (4, 5)
    assert find_python_symbol(src, "A.missing") is None
    assert find_python_symbol(src, "g") is None  # methods aren't top-level


def test_line_range_is_clamped_to_file(project):
    s = extract(project, CodeRef("calc.py", lines=(10, 999)))
    assert s["start"] == 10 and s["end"] == len((project / "calc.py").read_text().splitlines())


def test_whole_empty_file_is_not_an_error(project):
    write(project, "pkg/__init__.py", "")
    s = extract(project, CodeRef("pkg/__init__.py"))
    assert s["error"] is None and s["source"] == "" and s["start"] is None


def test_errors_are_reported_not_raised(project):
    write(project, "web/app.ts", "export const x = 1;\n")
    assert "not found" in extract(project, CodeRef("calc.py", symbol="nope"))["error"]
    assert "cannot read" in extract(project, CodeRef("missing.py"))["error"]
    assert "cannot read" in extract(project, CodeRef("../../etc/passwd"))["error"]
    assert "use 'lines'" in extract(project, CodeRef("web/app.ts", symbol="x"))["error"]
    assert "past the end" in extract(project, CodeRef("calc.py", lines=(500, 501)))["error"]
