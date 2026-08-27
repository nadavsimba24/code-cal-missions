"""Responses are gzipped — except the ones that must arrive as they are produced.

The SPA shell is ~650KB of HTML re-fetched on every entry, so compression is
most of what makes the app openable on a phone. The exception matters just as
much: Starlette's GZipMiddleware neither honours `no-transform` nor flushes
after each chunk, so compressing /api/events would hold every live event in a
buffer until the stream closed. Nothing else in the suite would notice.
"""


def test_the_spa_shell_is_compressed(client):
    plain = client.get("/", headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200
    # httpx decompresses transparently, so the bytes actually put on the wire
    # have to be read raw — otherwise this measures nothing.
    with client.stream("GET", "/", headers={"Accept-Encoding": "gzip"}) as gz:
        assert gz.status_code == 200
        assert gz.headers.get("content-encoding") == "gzip", "the shell is served uncompressed"
        sent = sum(len(c) for c in gz.iter_raw())
    assert sent < len(plain.content) / 2, (
        f"compression barely helped: {len(plain.content)}B -> {sent}B")


def test_a_client_that_cannot_decompress_still_gets_the_page(client):
    r = client.get("/", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert "content-encoding" not in {k.lower() for k in r.headers}
    assert r.text.lstrip().startswith("<!DOCTYPE html>")


def test_board_json_is_compressed(client, admin_id):
    r = client.get(f"/api/boards?user_id={admin_id}", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert r.json(), "compression broke the payload"


def test_the_event_stream_is_never_compressed():
    """The one that would break live updates silently.

    Asserted against the middleware's routing decision rather than by opening
    the stream: /api/events never ends by design, so a test client reading it
    would hang rather than fail. That the live server serves it uncompressed
    and streaming was checked separately with curl.
    """
    import main as cityos_main

    picked = []

    async def raw_app(scope, receive, send):
        picked.append("raw")

    mw = cityos_main.ConditionalGZip(raw_app)
    original_gzip = mw.gzip

    async def fake_gzip(scope, receive, send):
        picked.append("gzip")

    mw.gzip = fake_gzip

    def route(accept):
        picked.clear()
        scope = {"type": "http", "method": "GET", "path": "/api/events",
                 "headers": [(b"accept", accept.encode()),
                             (b"accept-encoding", b"gzip")]}
        import asyncio
        asyncio.run(mw(scope, None, None))
        return picked[0]

    assert route("text/event-stream") == "raw", \
        "the event stream is being gzipped — events will be buffered, not delivered"
    # and an ordinary request still goes through compression
    assert route("text/html,application/xhtml+xml") == "gzip"
    assert original_gzip is not None


def test_the_shell_carries_vary_so_caches_do_not_mix_the_two(client):
    """Without Vary, a shared cache can hand a gzipped body to a client that
    asked for plain text."""
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert "accept-encoding" in r.headers.get("vary", "").lower()


def test_a_repeat_entry_revalidates_instead_of_redownloading(client):
    """The complaint was about every entry, not the first one.

    `no-store` would forbid keeping the bytes at all, so the whole shell came
    down again each time. `no-cache` still forces a check with the server, so a
    deploy is picked up immediately — but an unchanged shell costs a round trip
    instead of ~180KB.
    """
    first = client.get("/")
    assert first.status_code == 200
    cc = first.headers.get("cache-control", "")
    assert "no-store" not in cc, "no-store forces a full re-download on every entry"
    assert "no-cache" in cc, "the shell must still be revalidated, never served blind"

    etag = first.headers.get("etag")
    assert etag, "without a validator the browser has nothing to revalidate with"
    again = client.get("/", headers={"If-None-Match": etag})
    assert again.status_code == 304, "an unchanged shell is being sent again in full"
    assert not again.content


def test_a_deploy_still_reaches_the_phone(client):
    """The risk of caching the shell: serving yesterday's app tomorrow."""
    stale = client.get("/", headers={"If-None-Match": '"from-an-older-deploy"'})
    assert stale.status_code == 200, "a stale validator was answered 304 — users would be stuck"
    assert stale.text.lstrip().startswith("<!DOCTYPE html>")
