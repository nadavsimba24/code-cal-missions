"""The doors a stranger can knock on answer 429 when knocked on too often.

The penetration test of 2026-11 sent runs of bad requests at sign-in and
guessed public-form tokens, and never met a 429 or a Retry-After. Pinned here:

  - the sign-in doors and the public forms are limited per client address,
    and the refusal says when to come back (Retry-After);
  - guessing form tokens — lookups that find nothing — spends a much smaller
    budget, after which the address gets no form answers at all;
  - unauthenticated /api/ noise is limited too, and a signed-in user from the
    SAME address is never refused by it;
  - the address is the one the front end appended to X-Forwarded-For, so
    writing a new first entry on every request does not reset the count.

Limits are lowered for the test; the counters are cleared afterwards so no
other test inherits them.
"""
import pytest

import main

H = lambda uid: {"X-CityOS-User": str(uid)}


@pytest.fixture
def small_limits(monkeypatch):
    main._rl_hits.clear()
    monkeypatch.setitem(main._RL_LIMITS, "auth", (3, 60))
    monkeypatch.setitem(main._RL_LIMITS, "form", (50, 60))
    monkeypatch.setitem(main._RL_LIMITS, "miss", (4, 600))
    monkeypatch.setitem(main._RL_LIMITS, "unauth", (5, 60))
    try:
        yield
    finally:
        main._rl_hits.clear()


def test_signing_in_is_limited_and_says_when_to_come_back(client, small_limits):
    codes = [client.get("/auth/callback?code=brute&state=x", follow_redirects=False).status_code
             for _ in range(5)]
    assert 429 not in codes[:3], codes
    assert codes[3:] == [429, 429], codes
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_guessing_form_tokens_runs_out_fast(client, small_limits):
    codes = [client.get(f"/api/public/forms/token-guess-{i}").status_code for i in range(6)]
    assert codes[:4] == [404] * 4, codes
    assert codes[4:] == [429, 429], codes


def test_unauthenticated_noise_is_limited_but_a_signed_in_user_is_not(client, small_limits, member_id):
    blank = {"X-CityOS-User": ""}
    codes = [client.get("/api/users", headers=blank).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429], codes
    # same address, a real identity: untouched
    assert client.get("/api/auth/me", headers=H(member_id)).status_code == 200


def test_a_forged_first_forwarded_address_does_not_reset_the_count(client, small_limits):
    codes = [client.get(f"/api/public/forms/guess-{i}",
                        headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7:5{i}000"}).status_code
             for i in range(6)]
    assert codes[4:] == [429, 429], codes
