import textwrap
from pathlib import Path

import pytest


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A tiny project with one documented feature, one passing and one failing test."""
    write(tmp_path, "calc.py", """
        import functools


        @functools.lru_cache()
        def add(a, b):
            return a + b


        class Calculator:
            def double(self, x):
                return x * 2
        """)
    write(tmp_path, "tests/test_calc.py", """
        import pytest
        from calc import add, Calculator


        @pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])
        def test_add(a, b):
            assert add(a, b) == a + b


        class TestCalculator:
            def test_double(self):
                assert Calculator().double(2) == 4

            def test_broken(self):
                assert Calculator().double(2) == 5
        """)
    # Make `import calc` work from the test file regardless of how pytest picks rootdir.
    write(tmp_path, "tests/conftest.py", """
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        """)
    write(tmp_path, ".agentbrief/features/addition.yaml", """
        id: addition
        title: Add two numbers
        summary: Adds numbers together.
        code:
          - path: calc.py
            symbol: add
        tests:
          - path: tests/test_calc.py
            symbol: test_add
        questions:
          - question: Does add cache its results?
            answer: Yes, it is wrapped in functools.lru_cache.
            about: calc.py::add
        """)
    return tmp_path
