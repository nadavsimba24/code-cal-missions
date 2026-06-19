# CityOS — Municipal Work Platform

## Overview
CityOS is an open-source Monday.com competitor built for Israeli municipalities.  
Combines project management, GIS mapping, BIM (3D modeling), AI agents, and real-time transport data.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python FastAPI + SQLAlchemy (SQLite → PostgreSQL) |
| Frontend | Vanilla JS SPA (no framework), 52KB index.html |
| Maps | MapLibre GL JS (from GeoLibre) |
| 3D/BIM | IfcOpenShell (IFC generation) + Three.js (viewer) |
| AI | Gemma 4 12B Coder via Ollama (local) |
| Animations | p5.js (particles background) |
| Transport | SIRI XML protocol (real-time public transport) |

## Project Structure

```
cityos/
├── backend/
│   ├── main.py          ← FastAPI server (port 8000, serves both API + frontend)
│   ├── models.py        ← SQLAlchemy models (15 tables: boards, tasks, permits, etc.)
│   ├── seed.py          ← Demo data for "עיריית הוד השרון"
│   ├── swarm.py         ← 6 AI agents that run on Gemma 4 via Ollama
│   └── bim_bridge.py    ← IFC/BCF generator (CityOS boards → 3D BIM models)
├── frontend/
│   └── index.html       ← Single-page application (RTL Hebrew)
├── GeoLibre/            ← Cloned repo (reference, not modified)
└── hod-hasharon-siri/   ← SIRI Python client for Israel's public transport API
```

## Running

```bash
cd ~/workspace/cityos
source venv/bin/activate
cd backend && python main.py
# → http://localhost:8000
```

## Key API Endpoints

- `GET /api/boards` — all boards with task counts & groups
- `GET /api/boards/{id}` — board with tasks, groups, assignees
- `GET /api/dashboard` — aggregated stats (tasks, overdue, citizen requests, permits)
- `GET /api/viz/board-insights` — per-board analytics for visualization
- `GET /api/graph/context` — knowledge graph (tasks + users + boards connections)
- `GET /api/forms/templates` — form templates (building permit, citizen request, event)
- `POST /api/swarm/think` — run AI agents (mode: single/all/coordinated)
- `GET /api/bim/generate?board_id=X` — generate IFC 3D model from board tasks
- `GET /api/bim/viewer-data` — Three.js-compatible JSON from latest IFC model
- `GET /api/transport/stops` — bus stops as GeoJSON (SIRI integration)
- `POST /api/tasks` — create task
- `POST /api/forms/submit` — submit form data → creates task

## Frontend Architecture

The frontend is a single HTML file with everything inline:
- No build step, no bundler
- CSS variables for theming
- RTL layout (Hebrew-first)
- All views rendered client-side from JSON data
- Views: Dashboard, Kanban Board, Map, Graph, Visualizations, Form Builder, BIM 3D Viewer

## AI Integration

Gemma 4 12B Coder runs locally via Ollama:
```bash
ollama run gemma4-coder "your prompt"
```

The Agent Swarm has 6 specialized agents:
- `builder` — project planning
- `transport` — public transport analysis
- `forms` — smart form generation
- `insights` — data analysis
- `viz` — visualization recommendations
- `predict` — timeline forecasting

## BIM Integration

CityOS can generate IFC (Industry Foundation Classes) models from task boards:
1. Tasks with GPS coordinates → 3D objects in local coordinate space
2. Tags determine object type (road, building, bus stop, light, park)
3. Priority determines object scale
4. BCF (BIM Collaboration Format) topics link tasks to IFC elements
5. Three.js viewer in the frontend renders the model

## Current Demo Data

- Municipality: **עיריית הוד השרון**
- 7 boards (infrastructure, transport, citizen requests, permits, business, parks, calendar)
- 9 tasks across boards
- 136 bus stops from OpenStreetMap
- 3 form templates
- 6 departments
- 7 users

## Development Notes

- The server automatically seeds demo data on first run (SQLite)
- To reset: delete `backend/cityos.db` and restart
- Frontend changes are hot-reloaded (no build step needed)
- All code is in this repo — the GeoLibre and SIRI directories are separate
