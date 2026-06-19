# CODE-CAL MISSIONS — Conventions (source of truth)

Shared contract between the **OpenClaw agent** (tasks via Telegram) and the
**dev session** (Claude Code). Keep both in sync. See also the coordination
section in the workspace `AGENTS.md`.

## Ownership split
| Layer | Owner | Files |
|---|---|---|
| **Data & content** | OpenClaw (Telegram) | `backend/seed*.py`, DB rows, scrapers, data sources |
| **Product (UI/agent/branding)** | Dev session | `frontend/index.html`, `backend/main.py` (AI + routes), `.env` |

The **integration point** is the SQLite DB (`backend/cityos.db`) + this file + git.
OpenClaw produces data; the dev session renders/serves it. Neither rewrites the other's lane.

## Hard invariants (enforced by `backend/sync.py`)
1. **Name = `CODE-CAL MISSIONS`** everywhere (never "CityOS").
2. **No purple.** Use the monday.com palette only:
   - blue `#0073ea` · green `#00c875` · orange `#fdab3d` · red `#e2445c` · light-blue `#579bfc` · grey `#c4c4c4`
3. **Fonts:** Figtree (Latin) + Rubik (Hebrew).
4. **Agent = DeepSeek** via `DEEPSEEK_API_KEY` in `.env` (`deepseek-chat` default). Local Ollama optional.
5. **Seeds are idempotent** — check existence before insert; never duplicate boards/tasks.

## Workflow after any change to cityos
```bash
python backend/sync.py     # reconcile colors + verify invariants
git add -A cityos && git commit -m "cityos: <what changed>"
bash run.sh                # restart server (loads .env + latest code)
python backend/healthcheck.py   # 19/19 endpoints + agent live
```

## Run
- Server: `bash run.sh` (detached, port 8000, loads `.env`).
- Health: `python backend/healthcheck.py`.
- Import a monday CSV as a board: `python backend/import_board.py`.
