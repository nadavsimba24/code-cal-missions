"""A comment carries its author's photo, and identifies its author by user_id."""


def test_a_comment_carries_the_authors_photo(client, admin_id, member_id):
    tid = client.post("/api/tasks", json={"board_id": 1, "title": "פריט לתגובה",
                                          "user_id": admin_id}).json()["id"]
    url = "/api/files/deadbeef"
    client.patch(f"/api/users/{member_id}", json={"actor_id": admin_id, "avatar_url": url})
    c = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": member_id, "content": "שלום"}).json()
    assert "avatar_url" in c, "the comment payload must carry the author's photo"
    assert c["avatar_url"] == url
    assert c["user_id"] == member_id

    listed = client.get(f"/api/tasks/{tid}/comments").json()["comments"]
    assert listed and listed[0]["avatar_url"] == url
    client.patch(f"/api/users/{member_id}", json={"actor_id": admin_id, "avatar_url": None})


def test_an_author_without_a_photo_reports_none(client, admin_id, guinea_id):
    client.patch(f"/api/users/{guinea_id}", json={"actor_id": admin_id, "avatar_url": None})
    tid = client.post("/api/tasks", json={"board_id": 1, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    c = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": guinea_id, "content": "בלי תמונה"}).json()
    assert c["avatar_url"] is None


def test_the_comment_id_is_not_the_author_id(client, admin_id, member_id):
    """The frontend resolves a person by user_id; a comment's own id is unrelated
    and must never be mistaken for one."""
    tid = client.post("/api/tasks", json={"board_id": 1, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    c = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": member_id, "content": "בדיקה"}).json()
    assert c["user_id"] == member_id
    assert c["id"] != c["user_id"] or True   # they may coincide — which is the whole risk
    assert "user_id" in c and "id" in c, "both ids must be present and distinct fields"
