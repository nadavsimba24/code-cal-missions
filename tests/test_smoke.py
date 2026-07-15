"""Group 1 — smoke: every core read endpoint returns 200 with a sane body."""
import pytest

# Endpoints verified to return 200 with the seeded demo data (no special auth).
READ_ENDPOINTS = [
    "/api/status",
    "/api/dashboard",
    "/api/boards",
    "/api/boards/1",
    "/api/users",
    "/api/departments",
    "/api/projects",
    "/api/tasks",
    "/api/permits",
    "/api/citizen-requests",
    "/api/kpis",
    "/api/work-plans",
    "/api/forms/templates",
    "/api/transport/stops",
    "/api/graph/context",
    "/api/viz/board-insights",
    "/api/viz/timeline",
    "/api/gantt/data?work_plan_id=1",
    "/api/audit-log",
    "/api/approvals",
    "/api/change-requests",
    "/api/dependencies",
    "/api/infrastructure/assets",
    "/api/ceo/dashboard",
    "/api/ceo/dashboard-enhanced",
    "/api/swarm/agents",
    "/api/ai/models",
    "/api/workspace/members",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_read_endpoint_ok(client, path):
    """Every core read endpoint responds 200 with valid JSON (parametrized)."""
    r = client.get(path)
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"
    # must be valid JSON
    r.json()


def test_status_shape(client):
    """/api/status reports {status: "ok"} — the basic health signal."""
    d = client.get("/api/status").json()
    assert d.get("status") == "ok"


def test_boards_list_nonempty(client):
    """/api/boards returns a non-empty list (demo data is seeded)."""
    boards = client.get("/api/boards").json()
    assert isinstance(boards, list) and len(boards) > 0


def test_board_detail_shape(client):
    """Board detail exposes the expected keys, incl. the owners field."""
    b = client.get("/api/boards/1?user_id=1").json()
    for key in ("id", "name", "groups", "tasks", "my_role", "owners"):
        assert key in b, f"board detail missing '{key}'"
