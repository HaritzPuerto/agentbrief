<!-- agentbrief:start -->
## Feature manifests (for human review)

A human reviews your work with Agentbrief (`agentbrief serve`). It shows each
feature as a plain-language explanation next to the exact code and the tests
that prove it. **When you add or change behavior, keep a manifest for it in
`.agentbrief/features/`.**

### Rules

1. **One file per user-visible feature**: `.agentbrief/features/<id>.yaml`. The `id` is
   lowercase kebab-case and matches the filename. Update the existing manifest
   when you change a feature; don't create a duplicate.
2. **Write `summary` for a non-expert human**: 1–3 sentences on *what it does
   and why*, not how. No jargon, no function names.
3. **`code` points at the implementation**: list each function or class that carries the
   feature. For Python, use `path` + `symbol` (`Class.method` for methods). For other
   languages, use `path` + `lines: "start-end"`. Point at the smallest unit that
   explains it, not at whole files. Add a short `note` when the role of a unit
   isn't obvious.
4. **`tests` points at the tests that pass for this feature**: pytest functions,
   given as `path` + `symbol` (`TestClass.test_name` for methods). Only list tests that
   actually exercise the feature, and add a `note` saying what each one checks.
   A feature marked `done` must have at least one test.
5. **`questions` let the human check they understood your change.** Before approving, they
   answer them, reveal your answer and grade themselves. Write 2–4 per feature (a `done`
   feature must have at least one):
   - Simple and concrete, answerable in one sentence by reading the code shown, e.g. "What
     happens if…?", "Which function decides…?", "What value does X get when Y?".
   - Focused on behavior that matters and on what you **just changed**, especially edge
     cases, failure paths and anything surprising. No trivia (names of variables, line numbers).
   - `answer`: short and correct. Add `about` (`path::symbol`) to say where to look.
   - When you change a feature's code, update its questions to match the new behavior.
6. **`status`** is one of `planned`, `in-progress` or `done`.
7. **Before you finish**, run `agentbrief check` and fix every error, then run
   `agentbrief test <id>` for the features you touched.
8. **Don't edit `.agentbrief/reviews.json`**. Only the human writes it. Changing reviewed
   code automatically marks that review as stale, which is expected.

### Refactors (reorganizing code without changing behavior)

When you move, rename, split, merge or extract code, write a manifest with
`kind: refactor` instead of hiding it inside a feature:

- **`base`**: the git commit *before* the reorganization (run `git rev-parse HEAD` before
  you start). The reviewer sees the old code from that commit, even after you commit.
- **`moves`**: one entry per moved or renamed unit, `from` (old location, at `base`) →
  `to` (new location, on disk). Leave out `from` for newly extracted code and `to` for
  deleted code. Add a `note` when the body changed on purpose and say why. The reviewer
  sees whether each body is unchanged.
- **`summary`**: why the reorganization helps, in plain language.
- **`tests`**: the tests that show behavior is preserved.
- **`questions`**: about the new layout, e.g. "Where does X live now?", "What was split out of Y?".
- Update every other manifest that pointed at the moved code (`agentbrief check` will flag the
  ones you miss).

```yaml
id: split-auth-module
kind: refactor
title: Split auth.py into login and password-reset modules
base: 3f2c1a9
summary: >
  auth.py had grown to 900 lines mixing two unrelated flows. Each flow now has
  its own module, so changes to password reset can't accidentally touch login.
moves:
  - from: app/auth.py::request_reset
    to: app/auth/reset.py::request_reset
  - from: app/auth.py::_check_pw
    to: app/auth/login.py::verify_password
    note: renamed; body unchanged
  - to: app/auth/__init__.py
    note: re-exports the old names so existing imports keep working
tests:
  - tests/test_auth.py
questions:
  - question: Where does the password-reset email get sent from now?
    answer: app/auth/reset.py, in request_reset.
```

### Template

```yaml
id: password-reset
title: Password reset by email
status: done
summary: >
  Users who forget their password can request a reset link by email.
  The link works once and expires after 30 minutes.
details: >            # optional: edge cases, design decisions, known limits
  Rate-limited to 3 requests per hour per address to prevent abuse.
code:
  - path: app/auth/reset.py
    symbol: request_reset
    note: creates the one-time token and sends the email
  - path: app/auth/reset.py
    symbol: ResetToken.is_valid
  - path: web/src/ResetForm.tsx
    lines: "12-58"
tests:
  - path: tests/test_reset.py
    symbol: test_reset_link_works_once
    note: second use of the same link is rejected
  - path: tests/test_reset.py
    symbol: TestExpiry.test_expired_link_rejected
questions:
  - question: What happens if someone clicks the same reset link twice?
    answer: The second click is rejected, because the token is deleted after its first use.
    about: app/auth/reset.py::ResetToken.is_valid
  - question: What does a user see if they request a reset for an email that isn't registered?
    answer: The same "check your inbox" message, so the form can't be used to find out which emails have accounts.
```
<!-- agentbrief:end -->
