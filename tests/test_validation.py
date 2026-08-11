"""Group 2 — input validation & error handling (regression guards for fixed bugs)."""


def test_create_task_empty_body_rejected(client):
    """Regression: an empty body used to silently create an orphan 'Untitled' task; now 422."""
    r = client.post("/api/tasks", json={})
    assert r.status_code == 422, r.text


def test_create_task_nonexistent_board_404(client):
    """Creating a task on a board that doesn't exist returns 404."""
    r = client.post("/api/tasks", json={"title": "x", "board_id": 999999})
    assert r.status_code == 404, r.text


def test_gantt_requires_work_plan_id(client):
    """Regression: /api/gantt/data without work_plan_id now returns a clear 400 (was 422)."""
    r = client.get("/api/gantt/data")
    assert r.status_code == 400, r.text


def test_gantt_with_param_ok(client):
    """/api/gantt/data with a valid work_plan_id returns 200."""
    assert client.get("/api/gantt/data?work_plan_id=1").status_code == 200


def test_nonexistent_board_404(client):
    """GET on a missing board id returns 404."""
    assert client.get("/api/boards/999999").status_code == 404


def test_nonexistent_project_404(client):
    """GET on a missing project id returns 404."""
    assert client.get("/api/projects/999999").status_code == 404


def test_nonexistent_form_template_404(client):
    """GET on a missing form template returns 404."""
    assert client.get("/api/forms/templates/999999").status_code == 404


def test_unknown_route_404(client):
    """An unknown API route returns 404 rather than a 500."""
    assert client.get("/api/definitely-not-a-real-route").status_code == 404
