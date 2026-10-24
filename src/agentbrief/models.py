"""Feature manifests: the contract between coding agents and Agentbrief.

Agents write one YAML file per feature under ``.agentbrief/features/``.
See ``templates/AGENTS_SECTION.md`` for the format they are told to follow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

import yaml

BRIEF_DIR = ".agentbrief"
FEATURES_DIR = "features"
STATUSES = ("planned", "in-progress", "done")
KINDS = ("feature", "refactor")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class CodeRef:
    path: str
    symbol: Optional[str] = None
    lines: Optional[Tuple[int, int]] = None
    note: Optional[str] = None

    @property
    def nodeid(self) -> str:
        """pytest node id for a test reference (``path::Class::test``)."""
        if not self.symbol:
            return self.path
        return self.path + "::" + self.symbol.replace(".", "::")


@dataclass
class Question:
    """A comprehension check the reviewer answers before approving."""
    question: str
    answer: str
    about: Optional[str] = None  # where to look, e.g. "app/auth.py::login"


@dataclass
class Move:
    """One step of a refactor: code that was moved, renamed, extracted (no ``before``) or removed (no ``after``)."""
    before: Optional[CodeRef] = None
    after: Optional[CodeRef] = None
    note: Optional[str] = None


@dataclass
class Feature:
    id: str
    title: str
    summary: str
    status: str = "done"
    details: str = ""
    code: List[CodeRef] = field(default_factory=list)
    tests: List[CodeRef] = field(default_factory=list)
    questions: List[Question] = field(default_factory=list)
    kind: str = "feature"
    moves: List[Move] = field(default_factory=list)
    base: Optional[str] = None  # git ref holding the "before" side of moves
    manifest: str = ""


def features_dir(root: Path) -> Path:
    return root / BRIEF_DIR / FEATURES_DIR


def _parse_lines(value: Any) -> Tuple[int, int]:
    if isinstance(value, int):
        return value, value
    if isinstance(value, (list, tuple)) and len(value) == 2:
        start, end = int(value[0]), int(value[1])
    elif isinstance(value, str):
        parts = value.replace(" ", "").split("-")
        if len(parts) == 1:
            start = end = int(parts[0])
        elif len(parts) == 2:
            start, end = int(parts[0]), int(parts[1])
        else:
            raise ValueError(f"bad line range {value!r}")
    else:
        raise ValueError(f"bad line range {value!r}")
    if start < 1 or end < start:
        raise ValueError(f"bad line range {value!r}")
    return start, end


def _parse_ref(raw: Any, where: str) -> CodeRef:
    if isinstance(raw, str):
        # Shorthand: "path/to/file.py::symbol" or just "path/to/file.py"
        path, _, symbol = raw.partition("::")
        return CodeRef(path=path, symbol=symbol.replace("::", ".") or None)
    if not isinstance(raw, dict) or "path" not in raw:
        raise ValueError(f"{where}: each entry needs a 'path'")
    lines = _parse_lines(raw["lines"]) if raw.get("lines") is not None else None
    return CodeRef(
        path=str(raw["path"]),
        symbol=raw.get("symbol") or None,
        lines=lines,
        note=raw.get("note") or None,
    )


def _parse_question(raw: Any) -> Question:
    if not isinstance(raw, dict) or not raw.get("question") or not raw.get("answer"):
        raise ValueError("questions: each entry needs a 'question' and an 'answer'")
    return Question(question=str(raw["question"]).strip(), answer=str(raw["answer"]).strip(),
                    about=str(raw["about"]) if raw.get("about") else None)


def _parse_move(raw: Any) -> Move:
    if not isinstance(raw, dict) or not (raw.get("from") or raw.get("to")):
        raise ValueError("moves: each entry needs a 'from', a 'to', or both")
    return Move(
        before=_parse_ref(raw["from"], "moves.from") if raw.get("from") else None,
        after=_parse_ref(raw["to"], "moves.to") if raw.get("to") else None,
        note=str(raw["note"]) if raw.get("note") else None,
    )


def parse_feature(data: Any, manifest: str) -> Feature:
    if not isinstance(data, dict):
        raise ValueError("manifest must be a YAML mapping")
    missing = [k for k in ("id", "title", "summary") if not data.get(k)]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    fid = str(data["id"])
    if not ID_RE.match(fid):
        raise ValueError(f"id {fid!r} must be lowercase kebab-case")
    status = str(data.get("status", "done"))
    if status not in STATUSES:
        raise ValueError(f"status {status!r} must be one of {', '.join(STATUSES)}")
    code = [_parse_ref(r, "code") for r in data.get("code") or []]
    tests = [_parse_ref(r, "tests") for r in data.get("tests") or []]
    questions = [_parse_question(q) for q in data.get("questions") or []]
    kind = str(data.get("kind", "feature"))
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} must be one of {', '.join(KINDS)}")
    moves = [_parse_move(m) for m in data.get("moves") or []]
    return Feature(
        id=fid,
        title=str(data["title"]),
        summary=str(data["summary"]).strip(),
        status=status,
        details=str(data.get("details") or "").strip(),
        code=code,
        tests=tests,
        questions=questions,
        kind=kind,
        moves=moves,
        base=str(data["base"]) if data.get("base") else None,
        manifest=manifest,
    )


def load_features(root: Path) -> Tuple[List[Feature], List[str]]:
    """Load every manifest. Returns (features, errors); bad files don't stop the rest."""
    features: List[Feature] = []
    errors: List[str] = []
    seen = {}
    fdir = features_dir(root)
    if not fdir.is_dir():
        return features, errors
    for path in sorted(list(fdir.glob("*.yaml")) + list(fdir.glob("*.yml"))):
        rel = path.relative_to(root).as_posix()
        try:
            feature = parse_feature(yaml.safe_load(path.read_text(encoding="utf-8")), rel)
        except (yaml.YAMLError, ValueError, TypeError) as exc:
            errors.append(f"{rel}: {exc}")
            continue
        if path.stem != feature.id:
            errors.append(f"{rel}: id {feature.id!r} must match the filename ({path.stem!r})")
            continue
        if feature.id in seen:
            errors.append(f"{rel}: duplicate id {feature.id!r} (also in {seen[feature.id]})")
            continue
        seen[feature.id] = rel
        features.append(feature)
    return features, errors
