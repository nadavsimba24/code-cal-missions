# CODE-CAL MISSIONS

A work-management platform (a monday.com equivalent) with an RTL Hebrew interface,
served as a single FastAPI app that hosts both the API and the SPA on port 8000.

> The product is named **CODE-CAL MISSIONS** everywhere a user can see it — never
> "CityOS". The old name survives internally as the wire format and must not be
> "fixed": `CITYOS_*` environment variables, the `X-CityOS-User` header, and
> `backend/cityos.db`.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI + SQLAlchemy, SQLite (`backend/cityos.db`) |
| Frontend | Vanilla-JS SPA — one `index.html`, inline CSS + JS, no framework, no build |
| Auth | Entra ID / Azure EasyAuth (`CITYOS_AUTH_MODE=easyauth`), dev picker locally |
| AI | DeepSeek via a server-side proxy; local Ollama swarm optional, usually off |
| Tests | pytest + `fastapi.testclient`, plus node `.mjs` harnesses over `index.html` |
| Deploy | Azure DevOps pipelines (QA + prod); Vercel serverless via `api/index.py` |
| Maps / BIM | MapLibre (GeoLibre WASM) · IfcOpenShell + Three.js |

## Layout

```
backend/
  main.py          ~24,000 lines — 221 routes, seeding, migrations, AI proxy, SSE
  models.py        ~1,560 lines — all SQLAlchemy tables and the status constants
  automations.py   the automation engine (triggers, conditions, actions, retry)
  auth.py          identity: current_user, auth_mode, effective_auth_mode
  entra.py         Entra ID / EasyAuth SSO      entra_guests.py  guest invitations
  filter_ast.py    the advanced-filter expression tree
  import_monday.py monday.com export → board import
  seed.py          demo data (idempotent)       healthcheck.py  endpoint sweep
frontend/
  index.html       ~19,600 lines — the whole SPA
  public-form.html the page a stranger filling in a form sees
  form-paper.js    shared form rendering        sortable.min.js  vendored, do not edit
  wasm/            GeoLibre map build, do not edit
tests/             234 test_*.py + 77 frontend/*.mjs harnesses + README.md
scripts/           security_agent.py, security_gate.sh, azure-deploy.sh, bench_views.py
api/index.py       Vercel serverless entrypoint around the same app
docs/              FORMS_PLAN.md, MONDAY_EXPORT_IMPORT.md, security review, releases/
CONVENTIONS.md     design + ownership invariants (source of truth)
```

## Commands

```bash
bash run.sh                             # restart the server detached on :8000, loads .env
./venv/bin/python backend/healthcheck.py  # endpoint sweep
./run_tests.sh                          # full suite + security gate
./run_tests.sh -q tests/test_x.py       # one file
./run_tests.sh -k automation            # by name
SKIP_SECURITY_GATE=1 ./run_tests.sh     # tests only
./venv/bin/python scripts/security_agent.py scan --only sast,secrets
```

`python main.py` has **no autoreload**. After a backend change, restart with
`bash run.sh` — a new route answering 404/405 is nearly always a stale process.

---

# Development workflow

For every **non-trivial** feature, run this end to end. The `/develop-feature`
skill executes it.

1. **Analyse** the requirements and dependencies — what is being asked, which
   lanes it touches, what already exists, what blocks what, where the risk is.
2. **Plan** — a short implementation plan: the change in a sentence, the files
   per lane, the order, and what "done" is tested by.
3. **Identify what can run in parallel** — work is parallel only when the agents
   touch disjoint files.
4. **Delegate** to the appropriate agents, launched in a single message so they
   run concurrently.
5. **Run the relevant automated tests.**
6. **Fix** what they find, routing each failure to the lane that owns the code.
7. **Final code review** with `code-reviewer` over the diff.
8. **Report**: what changed, test results, and anything unresolved.

## The agents

| Agent | Owns | Never touches |
|---|---|---|
| `backend-developer` | `backend/`, `api/` — routes, models, migrations, permissions, business logic | `frontend/`, `tests/` |
| `frontend-developer` | `frontend/` — views, JS, CSS, RTL, mobile, a11y | `backend/`, `tests/` |
| `qa-engineer` | `tests/` — pytest and `.mjs` harnesses; runs the suite | `backend/`, `frontend/` |
| `code-reviewer` | nothing — read-only review of the diff | everything (it never edits) |

**Two agents must never be given the same file.** `backend/main.py` and
`frontend/index.html` are single enormous files; concurrent edits clobber each
other. When the frontend depends on a response shape that does not exist yet,
sequence: backend first, then frontend and QA together.

## Rules

- **Follow the existing architecture and conventions.** They are strong here —
  read the surrounding code before adding to it.
- **Use the existing testing tools** — `./run_tests.sh`, pytest, the `.mjs`
  harness pattern. Do not introduce a new framework.
- **Avoid conflicting file edits** — one owner per file, per the table above.
- **Do not modify unrelated code.** No drive-by reformatting, re-sorting imports,
  or renaming. Keep the diff to the feature.
- **Do not deploy, push, merge, or modify production data without approval.**
  Pushing `main` is itself a QA deploy and needs an ask.
- **Ask when requirements are ambiguous** in a way that changes what gets built —
  before implementing, not after.
- **Avoid unnecessary delegation.** A typo, a constant, a one-line fix, a
  single-file change under ~30 lines: just do it, and run the tests.

---

# Invariants

Breaking one of these breaks the app or the build.

### Backend

1. **A new column needs an `ALTER TABLE`.** `init_db()` uses `create_all`, which
   does not add columns to an existing SQLite table. There is a hand-written
   additive-migration block near the top of `main.py` (~115 `ALTER TABLE`
   statements). A column added only to `models.py` works on a fresh DB and 500s
   on every existing one.
2. **Identity comes from the transport, never from a request parameter.** Resolve
   the actor with `current_user` / `current_user_id`. A `user_id` or `actor_id`
   parameter may name a *target*; it never says who is acting.
   `tests/test_authz.py` exists to catch this.
3. **Every route enforces permission explicitly**, via the existing helpers:
   `_ws_role`, `_board_role` / `_board_role_or_403`, `_require_board_edit`,
   `_is_board_admin`, `_item_perm`, `_can_see_item`, `_require_sys_admin`, and
   the automation `_can_manage_automations` family. Access is membership-based:
   a user sees only boards they were invited to.
4. **Correct status codes:** missing body → 422, unknown parent → 404, no
   permission → 403, bad argument → 400. Never a generic 500.
5. **Seeds stay idempotent** — check before insert, never duplicate.
6. **Never touch `backend/cityos.db`.** It is real working data (825MB) with
   hand-made backups beside it. Schema changes land as code.

### Frontend

7. **No purple.** monday palette only, through the CSS variables that already
   exist: `--primary #0073ea` · `--green #00c875` · `--orange #fdab3d` ·
   `--red #e2445c` · `--blue #579bfc` · `--yellow #ffcb00` · `--grey #c4c4c4`.
8. **Fonts:** Figtree (Latin) + Rubik (Hebrew). Already loaded; add no others.
9. **RTL-first** (`dir="rtl"`). Use logical properties — `margin-inline-start`,
   `inset-inline-end` — not `left`/`right`. UI strings Hebrew, code English.
10. **`esc()` every interpolated value.** An unescaped board or item name is
    stored XSS.
11. **The inline JS must parse** — `tests/test_assets.py` runs `node --check`
    over `index.html`.
12. **Readable on a phone, usable with a keyboard.** There are harnesses that
    fail if you regress it.
13. **No secret reaches the browser.** LLM keys are injected server-side in the
    `/api/llm/v1/chat/completions` proxy.

### Testing

14. `tests/conftest.py` redirects `CITYOS_DB_PATH` / `CITYOS_UPLOAD_DIR` to a temp
    dir **before** importing `main` (the app seeds at import), forces
    `CITYOS_AUTH_MODE=dev`, and blanks the mail keys to empty strings — not
    unset, because `load_dotenv` would refill an absent key and send real
    invitations.
15. **Tests are idempotent** — anything that mutates data restores it in a
    `finally`.
16. **Never edit a test to make a real failure pass.**

---

# Conventions

- **Comments explain _why_**, and what went wrong before — prose, often several
  lines. A bare `# set the flag` is out of place here.
- **Commit messages are prose sentences** describing the outcome, not
  conventional-commit prefixes. Recent history: *"Form View: a form is a view of
  a board, and a stranger can fill it in"*, *"Ask before the deletion, not
  explain after it"*.
- **Test names are sentences about behaviour**, and the module docstring says
  which rule is pinned and why it matters.
- **Backend code is grouped by helper family**; frontend code by domain object
  (`AI`, `SysAdmin`, `Workspace`, `Members`, `Chat`, `Profile`, `Auth`,
  `ItemPerms`). Put new behaviour where its area already lives.
- Frontend state is the global `st`; API calls go through the `api()` helper,
  which throws on a non-ok status.

## Two things that cost people hours

- **A stale browser tab looks exactly like a bug.** Hard-refresh (Cmd+Shift+R)
  before investigating a frontend change that "does not work".
- **A stale server answers 404 for a route that exists.** `bash run.sh`.

## Git and deploys

Branch `main`. Remotes: `origin` and `mashcal` (GitHub), `azure` (Azure DevOps).
Pushing `main` triggers the QA pipeline; prod is a manual pipeline against a
release branch. **Ask before any push, merge, or deploy, and ask which
environment** — never assume both.
