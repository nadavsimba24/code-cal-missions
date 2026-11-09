"""Clicking a file in the app saves it, instead of flashing a tab open and shut.

Every file link used to be `target="_blank"`. For anything the server refuses
to serve inline — an xlsx, a zip, a Word document — the browser opened a tab,
started the download and closed the tab again, which reads as the app
misbehaving; and for a PDF or a picture it left a tab standing that the reader
then had to close. The links now carry the `download` attribute and ask for
`?dl=1`, so the file lands in the downloads folder and the board stays put.

`dl` is what this pins on the server side: the attribute is advisory and some
browsers ignore it, and without the server saying "attachment" a PDF would
still open in the built-in viewer. The plain URL must keep answering `inline`,
because it is also what an <img> preview and a form's logo point at.
"""


def _as(uid):
    return {"X-CityOS-User": str(uid)}


def _upload(client, admin_id, name, data, ctype):
    up = client.post("/api/upload", files={"file": (name, data, ctype)},
                     headers=_as(admin_id))
    assert up.status_code == 200, up.text
    return up.json()["url"]


PNG = bytes.fromhex("89504e470d0a1a0a")


def test_a_picture_asked_for_as_a_download_comes_back_as_an_attachment(client, admin_id):
    url = _upload(client, admin_id, "חזית.png", PNG, "image/png")
    r = client.get(url + "?dl=1", headers=_as(admin_id))
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")


def test_the_same_picture_without_it_is_still_inline_for_the_preview(client, admin_id):
    """The thumbnail in a comment and the logo on a form are the same URL."""
    url = _upload(client, admin_id, "חזית.png", PNG, "image/png")
    r = client.get(url, headers=_as(admin_id))
    assert r.headers["content-disposition"].startswith("inline")


def test_a_pdf_is_saved_rather_than_opened_in_the_browsers_viewer(client, admin_id):
    url = _upload(client, admin_id, "תוכנית.pdf", b"%PDF-1.4\n", "application/pdf")
    assert client.get(url, headers=_as(admin_id)
                      ).headers["content-disposition"].startswith("inline")
    assert client.get(url + "?dl=1", headers=_as(admin_id)
                      ).headers["content-disposition"].startswith("attachment")


def test_the_download_keeps_the_hebrew_name_it_was_uploaded_with(client, admin_id):
    url = _upload(client, admin_id, "דוח בטיחות.pdf", b"%PDF-1.4\n", "application/pdf")
    disp = client.get(url + "?dl=1", headers=_as(admin_id)).headers["content-disposition"]
    assert "filename*=UTF-8''" in disp
    assert "%D7%93" in disp          # the name is there, percent-encoded


def test_a_file_that_was_never_inline_is_unchanged_by_the_flag(client, admin_id):
    """An .html upload is an opaque attachment with or without dl — the rule
    that keeps an uploaded page from executing on our origin is not weakened
    by the download flag passing through."""
    url = _upload(client, admin_id, "evil.html", b"<script>alert(1)</script>", "text/html")
    for u in (url, url + "?dl=1"):
        r = client.get(u, headers=_as(admin_id))
        assert r.headers["content-type"].startswith("application/octet-stream")
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.headers["x-content-type-options"] == "nosniff"


def test_the_download_still_needs_an_identity(client, admin_id):
    url = _upload(client, admin_id, "a.txt", b"hi", "text/plain")
    assert client.get(url + "?dl=1", headers={"X-CityOS-User": ""}).status_code == 401
