# CityOS — 🗺️ Roadmap & Vision

## Current State ✅
- [x] Monday.com-style Kanban boards (7 boards, 9 tasks)
- [x] Dashboard with stats & insights
- [x] MapLibre GL GIS map (bus stops, assets, tasks)
- [x] Obsidian-like knowledge graph (23 nodes)
- [x] p5.js particle animations
- [x] 6 Agent Swarm AI (Gemma 4)
- [x] Form builder (3 templates: building permit, citizen request, event)
- [x] Visualization dashboard (board analytics, timeline)
- [x] BIM 3D viewer (IFC generation + Three.js)
- [x] SIRI real-time transport data client
- [x] 136 bus stops from Hod HaSharon
- [x] RTL Hebrew UI

## Next Steps 🎯

### Phase 1 — Core Platform
- [ ] Drag & drop Kanban (HTML5 drag API)
- [ ] Real-time collaboration (WebSocket)
- [ ] Authentication / multi-tenant
- [ ] PostgreSQL support (production DB)

### Phase 2 — Municipal Features
- [ ] 4D BIM: task timelines → animated construction sequence
- [ ] 5D BIM: cost estimation from BOQ
- [ ] Automated BCF issue creation from citizen requests
- [ ] Workflow automation (when task done → notify + create next task)
- [ ] Calendar view (municipal events, hearings, inspections)

### Phase 3 — AI & Automation
- [ ] Auto-generate task breakdown from project title (Builder agent)
- [ ] Predictive delay detection (Predictor agent)
- [ ] Smart citizen request categorization
- [ ] Natural language board queries (chat with your project)

### Phase 4 — Integrations
- [ ] IfcOpenShell ↔ CityOS bidirectional (read IFC → create tasks)
- [ ] OpenProject BIM connector
- [ ] WhatsApp bot for citizen requests
- [ ] Email integration (new permit → create task)
- [ ] Government portal API (gov.il forms)

### Phase 5 — Scale
- [ ] Mobile app (React Native / Tauri)
- [ ] Multi-city dashboard
- [ ] Public portal (citizen-facing request tracker)
- [ ] Export/import (Excel, IFC, BCF, GTFS)
