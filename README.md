# Agentbrief

**Your coding agent briefs you on what it built.** Review what Claude Code (or any coding
agent) built, **feature by feature**. For each feature you see:

- **What it does**, in plain language written for a human,
- **The code** that implements it, extracted live from your files (with a git diff),
- **The tests** that prove it, with real pass/fail results from pytest,
- **Questions to check your understanding**: the agent writes a few simple questions
  about its change. You answer, reveal the real answer and grade yourself,
- **Your review**: approve or request changes. **Approve is enabled only after you've
  ticked every code block as checked and answered every question.** Your score is saved
  with the review. An approval is automatically marked *stale* if the agent later touches
  that code or those tests.

**Refactors** (code that was moved, renamed or split without new behavior) get their own
section. For every move you see the old code from git next to the new code, and whether the
body changed.

It also lists **changed files that no feature explains**, so an agent can't quietly change
things it didn't tell you about.

## How it works

```
 agent ──writes──▶ .agentbrief/features/<id>.yaml ◀──reads── agentbrief serve (web UI)
   ▲                   (summary, code refs, test refs)          │
   └── told how by AGENTS.md ◀── agentbrief init                       └─ runs pytest, git diff
```

Agents describe their work in small YAML manifests. The code and test results are never
copied into the manifests: Agentbrief reads the actual files and runs the actual
tests, so what you see is what's on disk.

## Quick start

```bash
pip install agentbrief   # into your project's environment (so it can run your tests)
cd your-project
agentbrief init          # creates .agentbrief/ and adds the manifest rules to AGENTS.md
                  # (and links CLAUDE.md -> AGENTS.md if CLAUDE.md exists; --claude creates it)
```

Then ask your agent:

> Read AGENTS.md and write feature manifests for what you built in this session.

And review:

```bash
agentbrief serve                  # opens http://localhost:8765
agentbrief serve --base main      # diff / "uncovered changes" against main instead of HEAD
```

## Commands

| command | what it does |
|---|---|
| `agentbrief init` | set up `.agentbrief/`, insert or refresh the rules block in `AGENTS.md` |
| `agentbrief check` | validate manifests: bad YAML, missing files or symbols, `done` features without tests. Exits 1 on errors. Agents run this. |
| `agentbrief test [ids…]` | run the tests listed by the given features (default: all) |
| `agentbrief serve` | open the review UI |
| `agentbrief hook stop` | Claude Code Stop hook entry point (installed by `init --claude-hook`) |

## Make Claude fix its manifests before it finishes

```bash
agentbrief init --claude-hook
```

This adds a [Stop hook](https://docs.claude.com/en/docs/claude-code/hooks) to
`.claude/settings.json`, merged with your existing settings. When Claude tries to end its
turn while `agentbrief check` reports errors, the hook exits with code 2, which sends Claude
back to work with the error list. Details:

- **No infinite loops:** Claude gets one forced retry per turn (`stop_hook_active`).
- **Finding `agentbrief`:** the launcher `.claude/hooks/agentbrief-stop.sh` looks in `.venv/bin`, then
  `venv/bin`, then `PATH`. If `agentbrief` isn't found, it does nothing.
- **Warnings don't block:** changed files that no feature explains are reported by
  `agentbrief check` but don't stop Claude.
- **macOS/Linux only:** the launcher is a POSIX shell script.

## Manifest format

```yaml
id: password-reset            # kebab-case, equals the filename
title: Password reset by email
status: done                  # planned | in-progress | done
summary: >                    # for humans: what and why, not how
  Users who forget their password can request a one-time reset link by email.
details: >                    # optional
  Links expire after 30 minutes.
code:
  - path: app/auth/reset.py
    symbol: request_reset     # Python: function, class or Class.method
    note: creates the token and sends the email
  - path: web/src/ResetForm.tsx
    lines: "12-58"            # other languages: line range
tests:
  - path: tests/test_reset.py
    symbol: TestExpiry.test_expired_link_rejected
    note: an expired link is refused
  - tests/test_reset.py::test_reset_link_works_once   # shorthand also works
questions:                    # 2–4 simple checks; a done feature needs at least one
  - question: What happens if someone clicks the same reset link twice?
    answer: The second click is rejected; the token is deleted after first use.
    about: app/auth/reset.py::ResetToken.is_valid   # optional: where to look
```

### Refactors

```yaml
id: split-auth-module
kind: refactor                # listed under "Refactors" instead of "Features"
base: 3f2c1a9                 # commit before the refactor; old code is read from here
summary: auth.py mixed two flows; each now has its own module.
moves:
  - from: app/auth.py::request_reset          # old location, at `base`
    to: app/auth/reset.py::request_reset      # new location, on disk
  - from: app/auth.py::_check_pw
    to: app/auth/login.py::verify_password    # renamed: the name alone isn't a body change
  - to: app/auth/__init__.py                  # no `from`: newly extracted code
tests: [tests/test_auth.py]
questions:
  - question: Where does the password-reset email get sent from now?
    answer: app/auth/reset.py, in request_reset.
```

Each move is shown as *moved / renamed / new / removed / edited* and marked **body unchanged**
or **body changed**, with a diff of just that function when it changed. Without `base`,
the old code is read from `agentbrief serve --base` (default `HEAD`). Approving a refactor
requires ticking every move as checked.

## Files

| path | owner | commit it? |
|---|---|---|
| `.agentbrief/features/*.yaml` | agent | yes |
| `.agentbrief/reviews.json` | you (via the UI) | yes, so reviews travel with the code |
| `.agentbrief/config.yaml` | you | optional, see below |
| `.agentbrief/.cache/` | tool | no (git-ignored by `init`) |

`config.yaml` (optional):

```yaml
test_command: ["uv", "run", "pytest"]   # default: <current python> -m pytest
pytest_args: ["-x"]
uncovered_ignore: ["README.md", "*.lock", "docs/*"]   # never flag these as unexplained
```

## Security

The server binds to `127.0.0.1`, only answers requests addressed to localhost, and
requires a per-session token for anything that writes or runs tests. Running tests runs
your project's code, the same as running `pytest` yourself.

## Current limits

- Symbol extraction works for Python only. For other languages, use `lines`.
- Test execution supports pytest only. Other runners (jest, cargo, …) are on the roadmap.

## License

MIT. See [LICENSE](LICENSE).
