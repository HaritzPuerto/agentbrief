import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentbrief.cli import HOOK_COMMAND, HOOK_SCRIPT, main

from conftest import write

BROKEN = """
    id: broken
    title: Broken
    summary: s
    code:
      - path: calc.py
        symbol: gone
    """


def stop_hook_commands(root):
    settings = json.loads((root / ".claude/settings.json").read_text())
    return [h["command"] for g in settings["hooks"]["Stop"] for h in g["hooks"]]


def test_install_merges_into_existing_settings_once(tmp_path):
    write(tmp_path, ".claude/settings.json", json.dumps({
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
                  "PreToolUse": []},
    }))
    assert main(["--root", str(tmp_path), "init", "--claude-hook"]) == 0
    assert main(["--root", str(tmp_path), "init", "--claude-hook"]) == 0
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert settings["model"] == "opus" and "PreToolUse" in settings["hooks"]
    assert stop_hook_commands(tmp_path) == ["say done", HOOK_COMMAND]
    assert os.access(tmp_path / HOOK_SCRIPT, os.X_OK)


def test_install_refuses_to_overwrite_unreadable_settings(tmp_path):
    write(tmp_path, ".claude/settings.json", "{ not json")
    assert main(["--root", str(tmp_path), "init", "--claude-hook"]) == 1
    assert (tmp_path / ".claude/settings.json").read_text() == "{ not json"


@pytest.mark.parametrize("stdin,broken,code", [
    ("{}", False, 0),
    ("{}", True, 2),
    ('{"stop_hook_active": true}', True, 0),  # loop guard
    ("not json", True, 2),
])
def test_hook_stop_exit_codes(project, monkeypatch, capsys, stdin, broken, code):
    if broken:
        write(project, ".agentbrief/features/broken.yaml", BROKEN)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(stdin))
    assert main(["--root", str(project), "hook", "stop"]) == code
    err = capsys.readouterr().err
    assert ("symbol 'gone' not found" in err) == (code == 2)


@pytest.mark.skipif(sys.platform == "win32", reason="launcher is a POSIX shell script")
def test_launcher_finds_project_venv_and_reports_to_claude(project):
    assert main(["--root", str(project), "init", "--claude-hook"]) == 0
    # Simulate the project's venv by linking the agentbrief we're testing into .venv/bin.
    agentbrief = shutil.which("agentbrief") or str(Path(sys.executable).parent / "agentbrief")
    (project / ".venv/bin").mkdir(parents=True)
    (project / ".venv/bin/agentbrief").symlink_to(agentbrief)
    write(project, ".agentbrief/features/broken.yaml", BROKEN)

    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PATH="/usr/bin:/bin")
    run = lambda stdin: subprocess.run([str(project / HOOK_SCRIPT)], input=stdin, env=env,
                                       capture_output=True, text=True, cwd="/")
    blocked = run('{"hook_event_name": "Stop", "stop_hook_active": false}')
    assert blocked.returncode == 2 and "symbol 'gone' not found" in blocked.stderr
    assert run('{"stop_hook_active": true}').returncode == 0

    (project / ".venv/bin/agentbrief").unlink()  # no agentbrief anywhere: never block
    assert run("{}").returncode == 0
