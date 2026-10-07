"""Group 12 — folders + environment-manager board management (delete, reorder)."""


def _setup_env_with_manager(client, admin_id, manager_id):
    env = client.post("/api/environments", json={"actor_id": admin_id, "name": "סביבת תיקיות"}).json()
    client.post(f"/api/environments/{env['id']}/members",
                json={"actor_id": admin_id, "user_id": manager_id, "role": "manager"})
    return env["id"]


def test_all_env_manager_actions_denied_to_plain_member(client, admin_id, guinea_id, member_id):
    """Every environment-manager capability must be refused (403) for a plain member
    of the environment, and succeed for the manager. This is the consolidated
    "only the environment manager" guard check."""
    env = client.post("/api/environments", json={"actor_id": admin_id, "name": "סביבת הרשאות"}).json()
    eid = env["id"]
    # guinea = environment manager, member_id = plain member (access only)
    client.post(f"/api/environments/{eid}/members", json={"actor_id": admin_id, "user_id": guinea_id, "role": "manager"})
    client.post(f"/api/environments/{eid}/members", json={"actor_id": admin_id, "user_id": member_id, "role": "member"})
    board_id = client.post("/api/boards", json={"name": "לוח בסביבה", "user_id": admin_id, "environment_id": eid}).json()["id"]
    fid = client.post("/api/folders", json={"actor_id": guinea_id, "environment_id": eid, "name": "ת"}).json()["id"]
    try:
        M, G = member_id, guinea_id   # plain member (denied), manager (allowed)

        # 1) create folder
        assert client.post("/api/folders", json={"actor_id": M, "environment_id": eid, "name": "x"}).status_code == 403
        assert client.post("/api/folders", json={"actor_id": G, "environment_id": eid, "name": "ok"}).status_code == 200
        # 2) rename folder
        assert client.patch(f"/api/folders/{fid}", json={"actor_id": M, "name": "x"}).status_code == 403
        assert client.patch(f"/api/folders/{fid}", json={"actor_id": G, "name": "ok"}).status_code == 200
        # 3) reorder boards/folders
        assert client.post(f"/api/environments/{eid}/reorder", json={"actor_id": M, "boards": [{"id": board_id, "position": 1}]}).status_code == 403
        assert client.post(f"/api/environments/{eid}/reorder", json={"actor_id": G, "boards": [{"id": board_id, "position": 1}]}).status_code == 200
        # 4) rename the environment
        assert client.patch(f"/api/environments/{eid}", json={"actor_id": M, "name": "x"}).status_code == 403
        assert client.patch(f"/api/environments/{eid}", json={"actor_id": G, "name": "ok"}).status_code == 200
        # 5) view/manage members
        assert client.get(f"/api/environments/{eid}/members?actor_id={M}").status_code == 403
        assert client.get(f"/api/environments/{eid}/members?actor_id={G}").status_code == 200
        # 6) add a member
        assert client.post(f"/api/environments/{eid}/members", json={"actor_id": M, "user_id": admin_id, "role": "member"}).status_code == 403
        # 7) delete a board in the environment
        assert client.delete(f"/api/boards/{board_id}?user_id={M}").status_code == 403
        assert client.delete(f"/api/boards/{board_id}?user_id={G}").status_code == 200
        board_id2 = None
        # 8) a manager still cannot hand out the manager role (sysadmin-only)
        assert client.patch(f"/api/environments/{eid}/members/{member_id}", json={"actor_id": G, "role": "manager"}).status_code == 403
    finally:
        # board may already be deleted by the test; ignore result
        client.delete(f"/api/boards/{board_id}?user_id={admin_id}")
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")


def test_folder_crud_by_env_manager(client, admin_id, guinea_id, member_id):
    """An environment manager can create/rename/delete folders; a plain member cannot."""
    eid = _setup_env_with_manager(client, admin_id, guinea_id)
    try:
        # plain member cannot create a folder
        client.post(f"/api/environments/{eid}/members",
                    json={"actor_id": admin_id, "user_id": member_id, "role": "member"})
        assert client.post("/api/folders", json={"actor_id": member_id, "environment_id": eid,
                                                 "name": "אסור"}).status_code == 403
        # manager creates a folder
        r = client.post("/api/folders", json={"actor_id": guinea_id, "environment_id": eid, "name": "תיקייה א"})
        assert r.status_code == 200, r.text
        fid = r.json()["id"]
        assert r.json()["can_manage"] is True
        # rename
        r = client.patch(f"/api/folders/{fid}", json={"actor_id": guinea_id, "name": "תיקייה ב"})
        assert r.status_code == 200 and r.json()["name"] == "תיקייה ב"
        # it shows up in the manager's folder list
        folders = client.get(f"/api/folders?user_id={guinea_id}").json()["folders"]
        assert any(f["id"] == fid for f in folders)
        # delete
        assert client.delete(f"/api/folders/{fid}?actor_id={guinea_id}").status_code == 200
    finally:
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")


def test_folder_delete_detaches_boards(client, admin_id, guinea_id):
    """Deleting a folder moves its boards to the environment root — never deletes them."""
    eid = _setup_env_with_manager(client, admin_id, guinea_id)
    board_id = None
    try:
        fid = client.post("/api/folders", json={"actor_id": guinea_id, "environment_id": eid, "name": "תיקייה"}).json()["id"]
        board_id = client.post("/api/boards", json={"name": "לוח בתיקייה", "user_id": guinea_id,
                                                    "environment_id": eid, "folder_id": fid}).json()["id"]
        # assign happened at creation
        b = next(x for x in client.get(f"/api/boards?user_id={admin_id}").json() if x["id"] == board_id)
        assert b["folder_id"] == fid
        # delete the folder → board survives, detached
        client.delete(f"/api/folders/{fid}?actor_id={guinea_id}")
        b = next(x for x in client.get(f"/api/boards?user_id={admin_id}").json() if x["id"] == board_id)
        assert b["folder_id"] is None
    finally:
        if board_id:
            client.delete(f"/api/boards/{board_id}?user_id={admin_id}")
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")


def test_env_manager_can_delete_board_and_reorder(client, admin_id, guinea_id):
    """An environment manager can delete a board they don't own, and reorder boards/folders."""
    eid = _setup_env_with_manager(client, admin_id, guinea_id)
    try:
        # admin creates a board (owned by admin) in the environment
        bid = client.post("/api/boards", json={"name": "לוח של אדמין", "user_id": admin_id,
                                              "environment_id": eid}).json()["id"]
        fid = client.post("/api/folders", json={"actor_id": guinea_id, "environment_id": eid, "name": "ת"}).json()["id"]
        # env manager reorders: move the board into the folder at position 0
        r = client.post(f"/api/environments/{eid}/reorder", json={
            "actor_id": guinea_id,
            "folders": [{"id": fid, "position": 0}],
            "boards": [{"id": bid, "folder_id": fid, "position": 0}],
        })
        assert r.status_code == 200, r.text
        b = next(x for x in client.get(f"/api/boards?user_id={admin_id}").json() if x["id"] == bid)
        assert b["folder_id"] == fid and b["position"] == 0
        # env manager deletes the admin-owned board
        assert client.delete(f"/api/boards/{bid}?user_id={guinea_id}").status_code == 200
        assert not any(x["id"] == bid for x in client.get(f"/api/boards?user_id={admin_id}").json())
    finally:
        client.delete(f"/api/environments/{eid}?actor_id={admin_id}")

# ── the + in the sidebar ────────────────────────────────────────────────────
# One button now makes both of the things the boards list holds. The folder icon
# beside it is gone: two icons for "add" is a guess the user has to decode, and
# the one that mattered most — a board built from a file — was behind neither of
# them. It lived in the menu of a board that already existed, which is the last
# place anyone looks for how to make one.
def _sidebar_src():
    import pathlib as _p
    return (_p.Path(__file__).resolve().parent.parent
            / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_plus_asks_board_or_folder_and_the_folder_icon_is_gone():
    src = _sidebar_src()
    assert "new-folder-btn" not in src, "the second add icon is gone, CSS and all"
    assert 'id="new-board-btn"' in src and 'onclick="newThingMenu(event)"' in src
    assert "function newThingMenu" in src
    # the first menu: the two things the list holds
    assert "fa-folder-plus\"></i> תיקייה" in src
    assert "fa-table-columns\"></i> לוח" in src
    # a folder still goes through the dialog that asks for its name
    assert "closeCellPops();Folders.create()" in src


def test_choosing_a_board_flies_out_sideways_rather_than_replacing_the_menu():
    """The choice already made stays on screen beside the one being made. Through
    the .pop-sub / .pop-subm pair every other nested menu here uses, so it opens
    leftwards in RTL, on hover and on click alike — the click being the only one
    that works by touch."""
    src = _sidebar_src()
    i = src.index("function newThingMenu")
    body = src[i:i + 2600]
    assert '<div class="pop-sub">' in body and '<div class="pop-subm">' in body
    assert "togglePopSub(event)" in body, "and by click, not only by hover"
    assert "pop-sub-caret" in body, "the row says it leads somewhere"
    assert "newBoardMenu" not in src, "no second menu that replaces the first"
    assert "closeCellPops();newBoardQuick()" in body, "לוח ריק"
    assert "closeCellPops();importBoardFile()" in body, "יצירת לוח מקובץ"
    assert "לוח ריק" in body and "יצירת לוח מקובץ" in body
    # the menu is anchored to the + itself
    assert "getElementById('new-board-btn')" in body and "openCellPop(btn," in body


def test_the_plus_shows_for_whoever_may_create_either():
    src = _sidebar_src()
    i = src.index("function updateNewBoardBtn")
    body = src[i:i + 500]
    assert "hasCap('create_board')||canFolder" in body, \
        "an environment manager who may not create boards still makes folders"
