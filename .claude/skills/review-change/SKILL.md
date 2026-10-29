---
name: review-change
description: Review the uncommitted changes in CODE-CAL MISSIONS with the code-reviewer subagent — bugs, security, regressions, quality — and report findings by severity with file:line references. Use when the user asks to review a change, check a diff, or sanity-check work before committing. Reports only; does not edit unless asked.
---

# Review a change

A review-only pass over work in progress. This is step 7 of `/develop-feature`
on its own — reach for it when there is nothing to build, only something to check.

## 1 — Scope the diff

```bash
git status --short
git diff              # unstaged
git diff --cached     # staged
```

Review **uncommitted work by default**. Other scopes only when the user names
one: a branch (`git diff main...HEAD`), a commit (`git show <sha>`), or a path.

If the diff is empty, say so and stop — do not go looking for something else to
review.

## 2 — Delegate to `code-reviewer`

Spawn the `code-reviewer` subagent. It already carries this project's review
criteria — the missing-`ALTER TABLE` trap, identity-from-transport, the
permission-helper family, `esc()` on interpolation, N+1 and board-render budgets,
the `CONVENTIONS.md` design invariants. **Do not restate them in the prompt.**

Give it only what it cannot work out for itself:

- which diff to review (the commands above, or the scope the user named)
- what the change was *meant* to do, if you know
- anything the user specifically wants looked at

For a large diff spanning both lanes, run two agents in one message — one scoped
to `backend/`, one to `frontend/` — and merge their findings. For anything
smaller, one agent.

## 3 — Run tests when it would change the verdict

Run them when the diff touches logic with existing coverage, or when a finding
is "this is broken" and a test would settle it:

```bash
./run_tests.sh -q tests/test_<subject>.py   # the files covering the change
SKIP_SECURITY_GATE=1 ./run_tests.sh         # whole suite, tests only
./venv/bin/python scripts/security_agent.py scan --only sast,secrets
```

Skip them for a docs or comment-only diff. The full suite is slow — target the
relevant files unless the change is broad. Never report a test result you did
not actually run.

## 4 — Report

Group by severity, most severe first:

- **Blocking** — ships a bug, a security hole, or a regression
- **Should fix** — real but survivable
- **Nit** — style and preference

Each finding: `file:line` as a clickable reference, one sentence on the defect,
and a concrete scenario where it fails. Separate what you **verified by running
something** from what you **inferred by reading**.

Close with a plain verdict: ready to commit, or what must change first. If the
diff is clean, say so in a line — do not pad the list with nits to look thorough.

## Do not fix

Report only. Apply a fix when the user asks — then route it to
`backend-developer` or `frontend-developer`, re-run the affected tests, and say
what changed. Never commit, push, or merge as part of a review.
