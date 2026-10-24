"""Pull the referenced source out of the project, live from disk."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import CodeRef

MAX_WHOLE_FILE_LINES = 400

LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".sh": "bash",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "ini", ".md": "markdown",
    ".html": "xml", ".css": "css", ".sql": "sql",
}


def resolve_in_root(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    if path != root.resolve() and root.resolve() not in path.parents:
        raise ValueError(f"{rel} is outside the project")
    return path


def find_python_symbol(source: str, dotted: str) -> Optional[Tuple[int, int]]:
    """Line span (1-based, inclusive, decorators included) of ``Class.method``-style names."""
    nodes = ast.parse(source).body
    target = None
    for part in dotted.split("."):
        target = next(
            (n for n in nodes
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part),
            None,
        )
        if target is None:
            return None
        nodes = target.body
    start = min([target.lineno] + [d.lineno for d in target.decorator_list])
    return start, target.end_lineno


def _read_at(root: Path, rel: str, git_ref: str) -> str:
    """File contents as of a git commit/branch."""
    resolve_in_root(root, rel)  # same path rules as files on disk
    if git_ref.startswith("-"):  # comes from a manifest; never let it become a git option
        raise OSError(f"invalid git ref {git_ref!r}")
    proc = subprocess.run(["git", "show", f"{git_ref}:{Path(rel).as_posix()}"], cwd=root,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise OSError(f"not in git at {git_ref}")
    return proc.stdout


def extract(root: Path, ref: CodeRef, git_ref: Optional[str] = None) -> Dict[str, Any]:
    """Return a snippet dict; problems are reported in ``error`` rather than raised.

    With ``git_ref`` the file is read from that commit instead of from disk.
    """
    snippet: Dict[str, Any] = {
        "path": ref.path, "symbol": ref.symbol, "note": ref.note,
        "language": LANGUAGES.get(Path(ref.path).suffix.lower(), "plaintext"),
        "start": None, "end": None, "source": "", "error": None, "truncated": False, "git_ref": git_ref,
    }
    try:
        if git_ref:
            text = _read_at(root, ref.path, git_ref)
        else:
            text = resolve_in_root(root, ref.path).read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        detail = str(exc) if git_ref and isinstance(exc, OSError) else exc.__class__.__name__
        snippet["error"] = f"cannot read {ref.path}: {detail}"
        return snippet
    lines = text.splitlines()

    if ref.lines:
        start, end = ref.lines
    elif ref.symbol:
        if snippet["language"] != "python":
            snippet["error"] = "symbol lookup only works for Python files; use 'lines' instead"
            return snippet
        try:
            span = find_python_symbol(text, ref.symbol)
        except SyntaxError as exc:
            snippet["error"] = f"cannot parse {ref.path}: {exc.msg} (line {exc.lineno})"
            return snippet
        if span is None:
            snippet["error"] = f"symbol {ref.symbol!r} not found in {ref.path}"
            return snippet
        start, end = span
    else:
        if not lines:  # whole empty file, e.g. a new __init__.py
            return snippet
        start, end = 1, len(lines)
        if end > MAX_WHOLE_FILE_LINES:
            end = MAX_WHOLE_FILE_LINES
            snippet["truncated"] = True

    if start > len(lines):
        snippet["error"] = f"line {start} is past the end of {ref.path} ({len(lines)} lines)"
        return snippet
    end = min(end, len(lines))
    snippet.update(start=start, end=end, source="\n".join(lines[start - 1:end]))
    return snippet
