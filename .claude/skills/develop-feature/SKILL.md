---
name: develop-feature
description: Run the full multi-agent feature workflow for CODE-CAL MISSIONS — analyse, plan, parallelise, delegate to the backend/frontend/QA agents, test, fix, review, report. Use when the user asks to build, change, or fix a non-trivial feature, or invokes /develop-feature.
---

# Develop a feature

The workflow for a non-trivial change in this repo. Run it end to end; do not
skip the test or review steps because the change "looks small".

## First: is this actually non-trivial?

Skip straight to doing the work yourself — no delegation, no plan document —
when the change is a typo, a one-line fix, a constant, a copy change, a question
about the code, or anything touching a single file in a single lane for under
~30 lines. Still run the relevant tests. Delegation has a real cost; spending it
on a one-liner is a worse outcome, not a more thorough one.

Everything below is for changes that span lanes, touch permissions or the data
model, or need more than one sitting.

## 1 — Analyse

Read before you plan. Establish:

- **What is being asked**, and what the acceptance condition is — how will we
  know it works?
- **Which lanes it touches**: `backend/` · `frontend/` · `tests/`.
- **What already exists.** `grep -n` for the route, the helper, the view. This
  codebase is large and repeats itself less than you would expect — there is
  usually already a place this belongs.
- **The dependencies.** Does the frontend need a response shape the backend
  does not return yet? Does a new column need an `ALTER TABLE`? Does it change
  a permission boundary?
- **The risk surface.** Permissions, identity, the automation engine, the
  monday import, and anything that touches the board render are the places where
  mistakes here are expensive.

**If the requirements are ambiguous in a way that changes what gets built, stop
and ask now.** Not after the implementation.

## 2 — Plan

Write a short plan — a handful of bullets, not a document:

- the change, in one sentence
- the files you expect to touch, per lane
- the order, and what blocks what
- what "done" is tested by

Show it to the user before delegating anything large.

## 3 — Identify what can run in parallel

Work is parallel when the agents touch **disjoint files**. The lane split is the
safe partition:

| Agent | Owns | Never touches |
|---|---|---|
| `backend-developer` | `backend/`, `api/` | `frontend/`, `tests/` |
| `frontend-developer` | `frontend/` | `backend/`, `tests/` |
| `qa-engineer` | `tests/` | `backend/`, `frontend/` |

**Two agents must never be given the same file.** `backend/main.py` and
`frontend/index.html` are single enormous files — concurrent edits to either
will clobber each other.

Sequence instead of parallelising when the frontend depends on a response shape
that does not exist yet: backend first, then frontend and QA together. When the
contract is already settled (you can state the endpoint and the JSON), all three
can run at once.

## 4 — Delegate

Launch independent agents **in a single message** so they run concurrently.
Give each one: the goal, the agreed contract (endpoint, payload, response), its
file boundary, and what to report. Do not give an agent a task outside its lane.

Do the work yourself instead when it is confined to one lane and small enough
that briefing an agent costs more than doing it.

## 5 — Test

```bash
./run_tests.sh -q tests/test_<subject>.py   # the targeted file, while iterating
./run_tests.sh                              # the full suite + security gate, before done
SKIP_SECURITY_GATE=1 ./run_tests.sh         # tests only
```

The full run is slow (234 pytest files, 77 node harnesses) — run it once, at the
end, not on every iteration. Restart the server with `bash run.sh` before any
manual check: `python main.py` has no autoreload, and a new route will answer
404 from the old process.

## 6 — Fix

Route each failure back to the lane that owns the code. Never change a test to
make a real failure pass. Re-run until green, and if something cannot be fixed,
say so explicitly rather than quietly narrowing the scope.

## 7 — Review

Run `code-reviewer` over the diff as the final gate. Act on blocking findings;
for the rest, decide and say what you decided. A review that produced findings
nobody acted on and nobody dismissed has not happened.

## 8 — Report

Close with:

- **Changed** — files, and what each change does
- **Tests** — the command, the counts, what is newly covered
- **Review** — what the reviewer raised and what you did about each
- **Open** — anything unresolved, skipped, or assumed, stated plainly
- **Not done** — anything in the original ask you did not deliver, and why

## Standing constraints

- Follow the existing architecture and conventions; this repo has strong ones.
- Keep the diff to the feature. No unrelated refactors, reformatting or renames.
- Never deploy, push, merge, or modify production data without explicit approval.
  Pushing `main` is a QA deploy — it needs an ask too.
- Never touch `backend/cityos.db`.

The full conventions, invariants and commands are in `CLAUDE.md`. Read it if any
of the above is unclear.
