"""Group — what an import's attachment fetch promises, over a real socket.

The import's only outbound calls are the attachments, and every guard around
them was put there after something went wrong: a url out of a file somebody
uploaded is an address this server will dial, so the host allow-list and the
https-only rule are the difference between a migration and an SSRF; a redirect
from an allowed host is that same hole with one hop in front of it; the per-file
ceiling is what stops a runaway link being read without end; the per-file
timeout bounds one file and the run-of-failures guard bounds a whole export
whose links have all expired; and `_fetch_import_file` never raising is what
lets the caller treat "expired", "blocked", "too big" and "timed out" as the one
thing they are to a person — an attachment that kept its name only.

Everything already pinned about this lives in test_import_files.py, and it is
pinned by standing in for the network: `_fetch_import_file` is replaced, or the
HTTP client it happens to use is. That is the right shape for testing what the
import does with the bytes, and the wrong shape for testing how the bytes are
got — a test that replaces the client's own `open` passes by construction no
matter what the fetch does with a 500, a redirect or a body of unbounded
length, and it stops even being runnable the day that client is swapped, which
is how this file came to be written.

So these run against a real HTTP server on a real TLS socket, and they only ever
speak to `_fetch_import_file` and `_prefetch_import_files` by their documented
behaviour: bytes or None, in the file's own order, within the budget. Nothing
here knows which client library does the fetching, which is the whole point —
this file is what says the guards still hold after that choice changes.

Two things are arranged so the stub can be reached at all, and neither touches
the product's own rules. Name resolution is pointed at 127.0.0.1 for the
duration, so the url carries monday's real asset host and goes through the real
`_import_host_allowed`; and certificate verification is relaxed at the moment a
socket is wrapped, which is the one seam every Python TLS client passes through,
rather than at a seam belonging to one of them. Because resolution is redirected
rather than blocked, a host that should have been refused would reach the stub
and be seen — a refusal is proved by the stub's silence, not assumed from it.
"""
import functools
import http.server
import ipaddress
import pathlib
import socket
import ssl
import struct
import tempfile
import threading
import time
import warnings
from datetime import datetime, timedelta, timezone

import pytest

import main as cityos_main

# monday's own asset host — the real one, so the real allow-list is what lets
# these fetches through. Only the resolution of the name is ours.
HOST = "files-monday-com.s3.amazonaws.com"
BLOB = b"%PDF-1.4 a file that came across\n"


# ── a stand-in for monday's S3, on a socket ────────────────────────────────

@functools.lru_cache(maxsize=1)
def _cert_file():
    """A self-signed certificate for the stub, made once per session.

    Its contents do not matter — the fixture relaxes verification — but a TLS
    server needs one, and generating it beats checking a key into the repo.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(who).issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName(HOST),
                 x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    out = pathlib.Path(tempfile.mkdtemp(prefix="import-asset-stub-")) / "stub.pem"
    out.write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                    + key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    return str(out)


class _Assets(http.server.BaseHTTPRequestHandler):
    """Every answer monday's S3 can give an import, including the bad ones."""

    protocol_version = "HTTP/1.1"
    server_version = "asset-stub/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        st = self.server.state
        with st["lock"]:
            st["seen"].append(self.path)
        try:
            self._answer(st)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            self.close_connection = True

    def _answer(self, st):
        path = self.path
        if path.startswith("/wait/"):             # /wait/<milliseconds>/<name>
            time.sleep(int(path.split("/")[2]) / 1000.0)
            return self._send(200, st["blob"], "application/pdf")
        if path == "/huge":
            return self._flood(st)
        if path == "/redirect/same-host":
            return self._moved(f"https://{HOST}:{st['port']}/ok/moved.pdf")
        if path == "/redirect/elsewhere":
            return self._moved("https://attacker.invalid/x.pdf")
        if path.startswith("/status/"):           # /status/<code>/<name>
            # Whatever S3 answers when a signature has lapsed or an asset is
            # gone — 401, 403, 410 — against the ones that say nothing about
            # the export, 429 and 503. Same shape either way; which side of the
            # line each falls on is the fetch's business, not the stub's.
            return self._send(int(path.split("/")[2]), b"<Error/>", "application/xml")
        if path == "/boom":                       # a server error, with a body
            return self._send(500, b"something went wrong", "application/pdf")
        if path == "/reset":
            return self._rst()
        if path.startswith("/login"):             # monday's sign-in page, as 200
            # By prefix, so a run of them can be a run of DIFFERENT urls — the
            # window fetches a set and would otherwise see one file asked for
            # sixty times.
            return self._send(200, b"<!DOCTYPE html><html>login</html>",
                              "text/html; charset=utf-8")
        if path.startswith("/ok/"):
            return self._send(200, st["blob"], "application/pdf")
        return self._send(404, b"", "text/plain")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _moved(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _flood(self, st):
        """A body far larger than any ceiling, written until somebody stops us.

        How much went out is the measurement: a fetch that reads to the end of
        this is a fetch with no ceiling at all.
        """
        total = st["huge_bytes"]
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(total))
        self.end_headers()
        chunk = b"x" * (256 * 1024)
        sent = 0
        try:
            while sent < total:
                self.wfile.write(chunk)
                sent += len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            with st["lock"]:
                st["sent"] = sent
            st["flooded"].set()
            self.close_connection = True

    def _rst(self):
        """The connection dropped mid-conversation, with no answer at all."""
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                       struct.pack("ii", 1, 0))
            self.connection.close()
        except OSError:
            pass
        self.close_connection = True


class _Stub(http.server.ThreadingHTTPServer):
    """The server, with its handshake off the accept loop.

    The usual recipe wraps the listening socket, which makes every TLS
    handshake happen inside the accept loop one at a time. An import fetches
    its files together, so that loop is where sixteen connections at once queue
    up behind each other — and on a machine that is busy with something else,
    the ones at the back are reset before they are ever accepted. Here the
    handshake happens in the connection's own thread instead.
    """

    daemon_threads = True
    request_queue_size = 128
    ssl_ctx = None

    def finish_request(self, request, client_address):
        try:
            tls = self.ssl_ctx.wrap_socket(request, server_side=True)
        except OSError:
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request, client_address):
        # A refused handshake and a connection a test dropped on purpose are
        # both ordinary here; a traceback per file would drown the run.
        pass


class _Monday:
    """The stub, as the test talks to it."""

    def __init__(self, state, resolved):
        self._st = state
        self.resolved = resolved

    @property
    def port(self):
        return self._st["port"]

    @property
    def seen(self):
        """Every path the stub was actually asked for, in arrival order."""
        with self._st["lock"]:
            return list(self._st["seen"])

    @property
    def blob(self):
        return self._st["blob"]

    @blob.setter
    def blob(self, value):
        self._st["blob"] = value

    @property
    def sent(self):
        with self._st["lock"]:
            return self._st["sent"]

    def wait_for_flood(self, seconds=15):
        return self._st["flooded"].wait(seconds)

    def url(self, path, host=HOST, scheme="https"):
        return f"{scheme}://{host}:{self.port}{path}"


@pytest.fixture
def monday(monkeypatch):
    """monday's asset host, answered locally, through the real allow-list."""
    state = {"lock": threading.Lock(), "seen": [], "blob": BLOB, "sent": 0,
             "huge_bytes": 64 * 1024 * 1024, "flooded": threading.Event()}
    srv = _Stub(("127.0.0.1", 0), _Assets)
    srv.state = state
    state["port"] = srv.server_port
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(_cert_file())
    srv.ssl_ctx = ctx
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    resolved = []
    real_getaddrinfo = socket.getaddrinfo

    def here(host, port, *a, **kw):
        resolved.append((host, port))
        return real_getaddrinfo("127.0.0.1", port, *a, **kw)

    real_wrap = ssl.SSLContext.wrap_socket

    def wrap(self, *a, **kw):
        # Relaxed at the moment of wrapping rather than at the moment of
        # building, because a pooled client builds its context once and long
        # before a test runs. check_hostname must go first — a context refuses
        # to drop verification while it still intends to check the name. The
        # stub's own side is left alone: it is wrapped from a connection's
        # thread, and several threads editing one context is a hazard nobody
        # here needs.
        if not kw.get("server_side"):
            try:
                self.check_hostname = False
                self.verify_mode = ssl.CERT_NONE
            except (ValueError, AttributeError):
                pass
        return real_wrap(self, *a, **kw)

    socket.getaddrinfo = here
    ssl.SSLContext.wrap_socket = wrap
    # The stub's certificate is its own and the client is told not to mind,
    # which some clients say so loudly that a run of this file is more warning
    # than output. Silenced by the text of it rather than by its class, so that
    # nothing here has to import a client library to quieten one.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Unverified HTTPS request.*")
        try:
            yield _Monday(state, resolved)
        finally:
            socket.getaddrinfo = real_getaddrinfo
            ssl.SSLContext.wrap_socket = real_wrap
            srv.shutdown()
            srv.server_close()


def _walk(win, urls):
    """What the import's walk sees: each file asked for in the file's order."""
    out = []
    for u in urls:
        out.append(win[u] if u in win else None)
    return out


# ── the guard on what may be dialled at all ────────────────────────────────

def test_a_file_on_mondays_own_host_comes_across_whole(monday):
    """The control. Everything below asserts that a fetch did NOT happen, and
    that is worth nothing unless a fetch that should happen does."""
    got = cityos_main._fetch_import_file(monday.url("/ok/spec.pdf"))
    assert got == (BLOB, "application/pdf"), got
    assert monday.seen == ["/ok/spec.pdf"]


def test_a_plain_http_address_is_not_dialled(monday):
    """https only. A pre-signed monday link is https; an http one is somebody
    else's address wearing monday's name, and the bytes would cross in clear."""
    assert cityos_main._fetch_import_file(monday.url("/ok/spec.pdf", scheme="http")) is None
    assert monday.resolved == [], "a connection was opened to a plain http address"
    assert monday.seen == []


def test_a_host_outside_the_allow_list_is_not_dialled(monday):
    """The url comes out of a file the user supplied. Without this the import is
    a request-forger: name 169.254.169.254 and the server reads its own cloud
    credentials for you."""
    for bad in ["https://attacker.invalid/x.pdf",
                "https://169.254.169.254/latest/meta-data/",
                "https://localhost/secret", "https://10.0.0.5/x",
                "https://127.0.0.1/x"]:
        assert cityos_main._fetch_import_file(bad) is None, bad
    assert monday.resolved == [], f"these addresses were dialled: {monday.resolved}"
    assert monday.seen == []


def test_a_host_that_merely_contains_mondays_name_is_not_dialled(monday):
    """Any host can be made to end in anything. `files-monday-com.s3.amazonaws.
    com.evil.test` is the attacker's domain and reads at a glance as monday's,
    which is exactly what a substring check would have let through."""
    for lookalike in [f"{HOST}.evil.test", f"{HOST}.attacker.invalid",
                      "monday.com.evil.test", "notmonday.com",
                      f"evil.test/{HOST}", f"{HOST}@evil.test"]:
        url = f"https://{lookalike}:{monday.port}/ok/spec.pdf"
        assert cityos_main._fetch_import_file(url) is None, lookalike
    assert monday.resolved == [], f"a look-alike host was dialled: {monday.resolved}"
    assert monday.seen == [], f"a look-alike host reached the server: {monday.seen}"


def test_a_redirect_from_an_allowed_host_is_not_followed(monday):
    """An allowed host that bounces the fetch elsewhere is the same hole with a
    hop in front of it, and a pre-signed asset link has no reason to redirect.
    Refused, not followed — including a redirect to another path on monday
    itself, because the fetch cannot tell the two apart from the inside."""
    assert cityos_main._fetch_import_file(monday.url("/redirect/elsewhere")) is None
    assert cityos_main._fetch_import_file(monday.url("/redirect/same-host")) is None
    assert monday.seen == ["/redirect/elsewhere", "/redirect/same-host"], \
        f"the redirect was followed: {monday.seen}"


# ── the ceilings around one file ───────────────────────────────────────────

def test_a_file_over_the_per_file_ceiling_does_not_come_across(monday, monkeypatch):
    """Over the ceiling means the attachment keeps its name only."""
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ONE_FILE_MB", 1)
    assert cityos_main._fetch_import_file(monday.url("/huge")) is None


def test_the_body_past_the_ceiling_is_never_read(monday, monkeypatch):
    """The ceiling is a ceiling on what is read, not on what is kept.

    A link of unbounded length is the thing this exists to survive, and reading
    all of it before measuring it is the same outage as having no ceiling —
    whatever the function then returns. So the stub offers sixty-four megabytes
    against a ceiling of one and counts what it managed to hand over: a fetch
    that stops reading cannot have taken much more than the socket's own
    buffers, and a fetch that drains the body to the end — to tidy a connection
    back into a pool, say — takes all of it.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ONE_FILE_MB", 1)
    assert cityos_main._fetch_import_file(monday.url("/huge")) is None
    assert monday.wait_for_flood(), "the stub never finished writing"
    # Generous: a megabyte asked for, buffers either side, and room to spare.
    assert monday.sent < 16 * 1024 * 1024, \
        f"{monday.sent} bytes were read for a file capped at 1MB"


def test_the_ceiling_is_the_last_size_that_still_comes_across(monday, monkeypatch):
    """Exactly the ceiling arrives; one byte more does not.

    The fetch asks for the ceiling and one byte, and a file that fills that one
    byte is the only evidence it has that there was more coming. Which side of
    the line each case lands on is the whole of the rule, and an off-by-one
    here is either an attachment refused for being exactly the allowed size or
    a ceiling that is not one.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ONE_FILE_MB", 1)
    cap = 1024 * 1024

    monday.blob = b"x" * cap
    got = cityos_main._fetch_import_file(monday.url("/ok/exactly.zip"))
    assert got is not None and len(got[0]) == cap, "a file of exactly the ceiling was refused"

    monday.blob = b"x" * (cap + 1)
    assert cityos_main._fetch_import_file(monday.url("/ok/one-over.zip")) is None, \
        "a file one byte over the ceiling came across"


def test_a_file_that_answers_slowly_is_given_up_on(monday, monkeypatch):
    """One file is bounded in time. Without it a hung host holds the whole
    import — and the import is one HTTP request, with somebody watching it."""
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_TIMEOUT", 1)
    started = time.monotonic()
    got = cityos_main._fetch_import_file(monday.url("/wait/8000/slow.pdf"))
    spent = time.monotonic() - started
    assert got is None
    assert spent < 5, f"the per-file timeout was not applied: {spent:.1f}s"


def test_a_connection_dropped_mid_fetch_is_a_failed_fetch(monday):
    """Not an exception. The import must go on to the next attachment."""
    assert cityos_main._fetch_import_file(monday.url("/reset")) is None


def test_a_server_error_is_a_failed_fetch_and_not_the_file(monday):
    """A 500 carries a body, and that body is not the attachment. Stored, it is
    a .pdf that opens and is somebody's error page — worse than a name on its
    own, because it looks like the file came across."""
    assert cityos_main._fetch_import_file(monday.url("/boom")) is None


def test_the_login_page_served_as_a_file_is_a_failed_fetch(monday):
    """A monday link that needs a session answers 200 with HTML, not 401."""
    assert cityos_main._fetch_import_file(monday.url("/login")) is None


def test_a_file_that_is_no_longer_there_is_a_failed_fetch(monday):
    """An expired or deleted asset — 404 — is an attachment that keeps its
    name, and never a raised exception."""
    assert cityos_main._fetch_import_file(monday.url("/missing.pdf")) is None


def test_nothing_the_fetch_meets_is_allowed_to_raise(monday, monkeypatch):
    """The caller's whole treatment of a failed attachment is `got is None`.

    Every one of these means the same thing to the import, which is why they are
    asserted together: the day one of them raises instead, a board stops
    importing at the first expired link rather than finishing with a name.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_TIMEOUT", 1)
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ONE_FILE_MB", 1)
    for url in [monday.url("/boom"), monday.url("/reset"), monday.url("/huge"),
                monday.url("/missing.pdf"), monday.url("/login"),
                monday.url("/redirect/elsewhere"),
                monday.url("/wait/3000/slow.pdf"),
                monday.url("/ok/x.pdf", scheme="http"),
                "https://attacker.invalid/x.pdf", "not a url at all", "", None]:
        assert cityos_main._fetch_import_file(url) is None, url


# ── the window: the walk's own order, the import's own budget ──────────────

def test_every_queued_file_reaches_the_walk_in_the_files_own_order(monday):
    """The window answers for each attachment in the order the items are read,
    and a file that could not be had answers None rather than going missing —
    the caller cannot tell a failed fetch from a fetch it never asked for, and
    must not have to."""
    urls = [monday.url(f"/ok/f{i}.pdf") if i % 4 else monday.url(f"/missing{i}.pdf")
            for i in range(12)]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=4)
    got = _walk(win, urls)
    assert [g is not None for g in got] == [bool(i % 4) for i in range(12)], got
    assert all(g == (BLOB, "application/pdf") for g in got if g), got
    assert len(monday.seen) == 12, monday.seen


def test_a_file_handed_to_the_walk_is_let_go_of(monday):
    """What the import holds is the window, not the board.

    A board of 972 attachments weighing 982MB is the case this is about: held to
    the end of the import, those bytes are the import's memory, and the ceiling
    that protected against it was the thing that left two thirds of that board
    as names.
    """
    monday.blob = b"z" * (256 * 1024)
    urls = [monday.url(f"/ok/h{i}.pdf") for i in range(16)]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=4)
    assert urls[0] in win
    before = win.held
    assert before >= len(monday.blob)
    win[urls[0]]
    assert win.held == before - len(monday.blob), "the file handed over is still held"
    for u in urls[1:]:
        assert u in win
        win[u]
    assert win.held == 0, f"{win.held} bytes are still held after the walk"


def test_a_run_of_failures_stops_the_import_trying(monday, monkeypatch):
    """When one link in a monday export has expired, all of them have.

    Discovering that three hundred times over cost three minutes of an import
    that had nothing else to do, so a run of failures stops the fetching. The
    rest of the queue is not attempted — that, and not the return value, is the
    whole point of the rule.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    urls = [monday.url(f"/missing{i}.pdf") for i in range(60)]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=4)
    assert _walk(win, urls) == [None] * 60
    # Up to one pool's worth are already in flight when the run trips; nothing
    # beyond that is a round trip anybody waited for.
    ceiling = (cityos_main.IMPORT_FILE_FAIL_STREAK
               + max(4, cityos_main.IMPORT_FILE_WORKERS) + 1)
    assert len(monday.seen) <= ceiling, \
        f"{len(monday.seen)} of 60 dead links were tried, expected at most {ceiling}"
    late = {f"/missing{i}.pdf" for i in range(40, 60)}
    assert not late & set(monday.seen), "the tail of the queue was tried anyway"


def test_one_file_that_comes_across_clears_the_run(monday, monkeypatch):
    """The guard is about an export that is wholly expired, not about a board
    with a few files missing — those must still carry everything else.

    Asked for one at a time, because a run of failures is a run of *completed*
    fetches and files fetched together complete in whatever order they finish
    in: with several in the air at once, two dead links and a live one can and
    do complete dead-dead-dead. The rule being pinned here is the counting, and
    one worker is the only arrangement in which the counting is observable.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    urls = []
    for i in range(12):
        urls += [monday.url(f"/missing{i}a.pdf"), monday.url(f"/missing{i}b.pdf"),
                 monday.url(f"/ok/g{i}.pdf")]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=1)
    got = _walk(win, urls)
    assert [g is not None for g in got] == [i % 3 == 2 for i in range(36)], got


# ── and what the run is allowed to count ───────────────────────────────────
# The guard above stops an import that cannot have its files. What it must not
# do is stop an import that is merely having a bad minute, and for a year it
# could not tell the difference: every failure counted alike.
#
# H3 חוזים is what that cost. 884 attachments; 509 came across and the report
# called the other 375 "לא נגישים" — monday no longer serves these — while 400
# of those very links fetched 400-for-400 from this machine, twice, minutes
# either side of the import. What had happened is that five fetches in a row
# timed out, which a loaded machine with big files, sixteen workers and a long
# write transaction holding SQLite produces on its own, and 367 live files were
# then abandoned without a single request being made for them.
#
# So only an answer that proves the link will never serve counts: 401, 403, 404,
# 410, or monday's sign-in page handed over as a 200. These run against a server
# that really gives each of those answers, because the whole of the rule is
# which answer means which thing.

# The dead answers, each as a run of distinct urls. 404 is the existing test
# just above; what is added here is everything else that condemns an export.
DEAD_ANSWERS = {
    "a signature S3 refuses": "/status/403/f{}.pdf",
    "an asset that wants a session": "/status/401/f{}.pdf",
    "an asset deleted for good": "/status/410/f{}.pdf",
    "monday's sign-in page, as a 200": "/login?f={}",
}


@pytest.mark.parametrize("answer", sorted(DEAD_ANSWERS), ids=lambda s: s.replace(" ", "-"))
def test_a_run_of_dead_answers_still_stops_the_import_trying(monday, monkeypatch, answer):
    """The behaviour the guard exists for, and it must not have been lost.

    A wholly stale export answers one of these to every link in it. Narrowing
    what counts is only safe if each of these still counts — otherwise an
    export exported yesterday spends a round trip per file being told so, which
    is the three minutes the rule was written to save.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    urls = [monday.url(DEAD_ANSWERS[answer].format(i)) for i in range(60)]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=4)
    assert _walk(win, urls) == [None] * 60
    ceiling = (cityos_main.IMPORT_FILE_FAIL_STREAK
               + max(4, cityos_main.IMPORT_FILE_WORKERS) + 1)
    assert len(monday.seen) <= ceiling, \
        f"{len(monday.seen)} of 60 dead links were tried, expected at most {ceiling}"


def test_a_run_of_timeouts_does_not_stop_the_import_trying(monday, monkeypatch):
    """H3 חוזים, in miniature: the files after a bad patch are still asked for.

    A timeout is evidence about this minute and not about the export — the link
    was never answered, so nothing was learned about it — and treating it as a
    verdict is what abandoned 367 attachments that were there the whole time.
    Six in a row, against a run of three: under the old rule the twelve files
    behind them were never dialled.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_TIMEOUT", 1)
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    slow = [monday.url(f"/wait/6000/t{i}.pdf") for i in range(6)]
    after = [monday.url(f"/ok/after{i}.pdf") for i in range(12)]
    win = cityos_main._prefetch_import_files(slow + after,
                                             [18, 64 * 1024 * 1024], workers=4)
    got = _walk(win, slow + after)
    assert got[:6] == [None] * 6, "the slow files were supposed to time out"
    assert got[6:] == [(BLOB, "application/pdf")] * 12, \
        "a run of timeouts condemned the files behind it"
    seen = set(monday.seen)
    missing = [f"/ok/after{i}.pdf" for i in range(12) if f"/ok/after{i}.pdf" not in seen]
    assert not missing, f"these files were never asked for at all: {missing}"


def test_an_answer_that_says_try_again_does_not_count_either(monday, monkeypatch):
    """429 and 503 are monday saying "not now", not "not ever".

    They are the cheap half of the same mistake — they arrive promptly, so
    nothing is saved by giving up on them, and a board that meets a rate limit
    partway down must finish rather than report its remaining files as gone.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    busy = [monday.url(f"/status/{429 if i % 2 else 503}/b{i}.pdf") for i in range(8)]
    after = [monday.url(f"/ok/later{i}.pdf") for i in range(6)]
    win = cityos_main._prefetch_import_files(busy + after,
                                             [14, 64 * 1024 * 1024], workers=4)
    got = _walk(win, busy + after)
    assert got[:8] == [None] * 8
    assert got[8:] == [(BLOB, "application/pdf")] * 6, "a busy minute condemned the board"


def test_one_file_that_comes_across_clears_a_run_of_any_kind(monday, monkeypatch):
    """A success resets both runs the guard keeps, not only the dead one.

    The backstop below counts failures of every kind, and it has to be a run:
    an import that meets trouble every third file for an hour is an import that
    is working, and nothing about it says the network has gone. Asked one at a
    time, because a run is a run of completed fetches and files in the air
    together complete in whatever order they finish in.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_GIVE_UP_STREAK", 3)
    urls = []
    for i in range(10):
        urls += [monday.url(f"/status/503/s{i}a.pdf"), monday.url(f"/status/503/s{i}b.pdf"),
                 monday.url(f"/ok/clear{i}.pdf")]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=1)
    got = _walk(win, urls)
    assert [g is not None for g in got] == [i % 3 == 2 for i in range(30)], got


def test_a_run_long_enough_is_given_up_on_whatever_it_is_made_of(monday, monkeypatch):
    """The backstop, and the only thing that bounds the pathological case.

    Once a timeout stops counting as a verdict, a board whose every attachment
    times out costs a timeout per attachment: 900 of them at twenty seconds
    apiece, sixteen at a time, is eighteen minutes of a request somebody is
    sitting in front of. A run this long of failures of any kind is the network
    being gone rather than a bad minute, so it stops. Turned right down here —
    at its shipped value of a hundred this test would be a hundred round trips.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 50)   # out of the way
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_GIVE_UP_STREAK", 6)
    urls = [monday.url(f"/status/503/g{i}.pdf") for i in range(60)]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=4)
    assert _walk(win, urls) == [None] * 60
    ceiling = (cityos_main.IMPORT_FILE_GIVE_UP_STREAK
               + max(4, cityos_main.IMPORT_FILE_WORKERS) + 1)
    assert len(monday.seen) <= ceiling, \
        f"{len(monday.seen)} of 60 files were tried, expected at most {ceiling}"
    late = {f"/status/503/g{i}.pdf" for i in range(40, 60)}
    assert not late & set(monday.seen), "the tail of the queue was tried anyway"


def test_the_fetch_leaves_a_verdict_the_guard_can_read(monday, monkeypatch):
    """The seam itself, since every rule above rests on it.

    `_fetch_import_file` answers bytes-or-None and says no more than that —
    which is what lets the rest of the suite stand in for it with a one-line
    function — so the reason is left beside the return value, on this thread.
    Absent, a failure counts as dead: a stand-in that records nothing must not
    be able to switch the guard off.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_TIMEOUT", 1)
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ONE_FILE_MB", 1)
    for url in [monday.url("/status/401/x.pdf"), monday.url("/status/403/x.pdf"),
                monday.url("/status/404/x.pdf"), monday.url("/status/410/x.pdf"),
                monday.url("/login")]:
        assert cityos_main._fetch_import_file(url) is None, url
        assert cityos_main._import_fetch_was_dead() is True, \
            f"{url} should condemn the export and did not"
    for url in [monday.url("/boom"), monday.url("/status/429/x.pdf"),
                monday.url("/status/503/x.pdf"), monday.url("/reset"),
                monday.url("/wait/5000/slow.pdf"), monday.url("/huge"),
                monday.url("/redirect/elsewhere"), "not a url at all", "", None]:
        assert cityos_main._fetch_import_file(url) is None, url
        assert cityos_main._import_fetch_was_dead() is False, \
            f"{url} is this import having a bad minute, not a verdict on the export"
    # A fetch that worked says nothing about any of it, and clears the run by
    # having worked.
    assert cityos_main._fetch_import_file(monday.url("/ok/fine.pdf")) is not None


def test_a_failure_with_no_verdict_recorded_counts_as_dead(monkeypatch):
    """The default, stated on its own because the whole suite relies on it.

    Most of tests/test_import_files.py replaces `_fetch_import_file` with a
    function that answers None and records nothing. If an unrecorded failure
    were transient, that file would be testing an import with no give-up guard
    at all, and the guard could be deleted without a single test noticing.
    """
    monkeypatch.delattr(cityos_main._IMPORT_FETCH, "why", raising=False)
    assert cityos_main._import_fetch_was_dead() is True


def test_nothing_past_the_file_ceiling_is_fetched(monday):
    """The budget's first number is files, and a prefetch that pulled more than
    the import may keep would spend exactly the time it exists to save."""
    urls = [monday.url(f"/ok/c{i}.pdf") for i in range(40)]
    win = cityos_main._prefetch_import_files(urls, [6, 64 * 1024 * 1024], workers=4)
    got = _walk(win, urls)
    assert [g is not None for g in got] == [True] * 6 + [False] * 34, got
    assert len(monday.seen) == 6, f"{len(monday.seen)} files were fetched for a budget of 6"


def test_nothing_past_the_byte_budget_is_fetched(monday):
    """The budget's second number is bytes, shared by the whole import.

    It stops where it stops — the files below that point keep their names, and
    the import says so — but what it must never do is fetch the rest anyway and
    throw the bytes away, which costs the round trip and the memory both.

    Not to the byte, and not even to the file: the attachments are in the air
    together, so a whole pool's worth can be past the budget's gate before the
    first of them has been subtracted, and the import's own walk refuses a
    second time what it cannot afford. What is pinned is the shape — the budget
    stops the fetching, and the tail of a board eight times the budget is never
    asked for at all.
    """
    monday.blob = b"q" * (512 * 1024)
    urls = [monday.url(f"/ok/b{i}.pdf") for i in range(64)]
    win = cityos_main._prefetch_import_files(urls, [len(urls), 4 * 1024 * 1024],
                                             workers=4)
    got = _walk(win, urls)
    arrived = [g for g in got if g]
    ceiling = 8 + max(4, cityos_main.IMPORT_FILE_WORKERS) + 1
    assert 8 <= len(arrived) <= ceiling, f"{len(arrived)} files for a budget of eight"
    assert len(monday.seen) <= ceiling, \
        f"{len(monday.seen)} of 64 files were fetched for a budget of eight"
    late = {f"/ok/b{i}.pdf" for i in range(32, 64)}
    assert not late & set(monday.seen), "a file far past the budget was fetched"


# ── and the reason any of this is being rewritten ──────────────────────────

def test_a_slow_file_does_not_hold_up_the_files_behind_it(monday):
    """The attachments are waited for together, not one after another.

    A board's files are the import's only outbound calls and they do not depend
    on each other, so the wait is the one thing worth overlapping: 307 live S3
    links fetched one at a time is minutes of a request somebody is watching.
    One slow file is what tests that — serially this set costs four seconds plus
    twenty-three files of three hundred milliseconds each, near eleven seconds;
    overlapped eight at a time it costs about the slow one. The bound is loose
    on purpose, so that a busy machine fails it only when the overlapping is
    genuinely gone — and it is still less than half of what one-at-a-time costs.
    """
    urls = ([monday.url("/wait/4000/slow.pdf")]
            + [monday.url(f"/wait/300/fast{i}.pdf") for i in range(23)])
    started = time.monotonic()
    win = cityos_main._prefetch_import_files(urls, [len(urls), 64 * 1024 * 1024],
                                             workers=8)
    got = _walk(win, urls)
    spent = time.monotonic() - started
    assert all(g == (BLOB, "application/pdf") for g in got), "a file did not arrive"
    assert spent < 7.5, (f"the set took {spent:.1f}s — serially it is near 11s, "
                         "and overlapped it is about the slow file alone")
