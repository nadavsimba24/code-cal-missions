"""Outgoing mail: which provider sends, and what exactly goes on the wire.

The app has one way out (`main._send_email`) and two providers behind it. These
tests pin the part that is easy to get wrong and impossible to see from the
outside: that the provider is chosen by configuration alone, that each one gets
the payload *it* expects, and that a half-configured environment sends nothing
rather than something that will bounce.

Nothing here touches the network — urlopen is replaced, and the request it was
handed is the assertion.
"""
import json
import urllib.request

import pytest

import main as cityos_main

MAIL_ENV = ("SENDGRID_API_KEY", "RESEND_API_KEY", "MAIL_PROVIDER",
            "INVITE_FROM_EMAIL", "EMAIL_DEV_REDIRECT", "SENDGRID_SANDBOX")


@pytest.fixture
def mail_env(monkeypatch):
    """A machine with no mail configured at all — each test adds what it needs.

    The developer's own .env may well hold a real key; left in place it would
    decide these tests for them.
    """
    for k in MAIL_ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.fixture
def sent(monkeypatch):
    """Capture the request instead of sending it. Returns a list of calls."""
    calls = []

    class _Resp:
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url,
                      "headers": {k.lower(): v for k, v in req.headers.items()},
                      "body": json.loads(req.data.decode("utf-8"))})
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    return calls


def test_no_keys_sends_nothing(mail_env, sent):
    """Mail that was never configured is dropped, and an invite still works."""
    assert cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>") is False
    assert sent == []


def test_sendgrid_payload(mail_env, sent):
    """A SendGrid key is enough to pick SendGrid, and its shape is v3's."""
    mail_env.setenv("SENDGRID_API_KEY", "SG.test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "CityOS <no-reply@mashcal.co.il>")

    assert cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>") is True

    assert len(sent) == 1
    call = sent[0]
    assert call["url"] == "https://api.sendgrid.com/v3/mail/send"
    assert call["headers"]["authorization"] == "Bearer SG.test-key"
    assert call["body"]["personalizations"] == [{"to": [{"email": "a@b.co.il"}]}]
    assert call["body"]["from"] == {"email": "no-reply@mashcal.co.il", "name": "CityOS"}
    assert call["body"]["subject"] == "נושא"
    assert call["body"]["content"] == [{"type": "text/html", "value": "<p>שלום</p>"}]
    # sandbox is off unless asked for: a real deploy must really deliver
    assert "mail_settings" not in call["body"]


def test_sendgrid_sandbox_mode(mail_env, sent):
    """SENDGRID_SANDBOX validates the send — sender identity included — and
    delivers nothing, which is how a deploy proves mail is wired up."""
    mail_env.setenv("SENDGRID_API_KEY", "SG.test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "no-reply@mashcal.co.il")
    mail_env.setenv("SENDGRID_SANDBOX", "1")

    cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>")

    assert sent[0]["body"]["mail_settings"] == {"sandbox_mode": {"enable": True}}
    # a bare address carries no display name, and SendGrid rejects an empty one
    assert sent[0]["body"]["from"] == {"email": "no-reply@mashcal.co.il"}


def test_resend_still_sends_its_own_shape(mail_env, sent):
    """The provider that was here first is untouched — same endpoint, same body."""
    mail_env.setenv("RESEND_API_KEY", "re_test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "CityOS <no-reply@mashcal.co.il>")

    assert cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>") is True

    call = sent[0]
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"]["authorization"] == "Bearer re_test-key"
    assert call["body"]["from"] == "CityOS <no-reply@mashcal.co.il>"
    assert call["body"]["to"] == ["a@b.co.il"]


def test_sendgrid_wins_when_both_keys_are_set(mail_env, sent):
    """An environment given a SendGrid key was given one on purpose."""
    mail_env.setenv("SENDGRID_API_KEY", "SG.test-key")
    mail_env.setenv("RESEND_API_KEY", "re_test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "no-reply@mashcal.co.il")

    cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>")

    assert sent[0]["url"] == "https://api.sendgrid.com/v3/mail/send"


def test_named_provider_without_its_key_does_not_fall_back(mail_env, sent):
    """MAIL_PROVIDER is a decision, not a preference. Naming a provider whose
    key is missing is a misconfiguration to find in the log — not a reason to
    send through the other one, which nobody chose."""
    mail_env.setenv("MAIL_PROVIDER", "sendgrid")
    mail_env.setenv("RESEND_API_KEY", "re_test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "no-reply@mashcal.co.il")

    assert cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>") is False
    assert sent == []


def test_sendgrid_refuses_resends_sandbox_sender(mail_env, sent):
    """The default From belongs to Resend's shared domain. SendGrid rejects any
    sender it has not verified, so a key set without a sender sends nothing and
    says so, instead of every message coming back 403."""
    mail_env.setenv("SENDGRID_API_KEY", "SG.test-key")   # INVITE_FROM_EMAIL left unset

    assert cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>") is False
    assert sent == []


def test_dev_redirect_applies_to_sendgrid_too(mail_env, sent):
    """The redirect is the app's, not a provider's: one verified inbox gets the
    message and the real recipient stays named in the subject."""
    mail_env.setenv("SENDGRID_API_KEY", "SG.test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "no-reply@mashcal.co.il")
    mail_env.setenv("EMAIL_DEV_REDIRECT", "qa@mashcal.co.il")

    cityos_main._send_email("real@b.co.il", "נושא", "<p>שלום</p>")

    body = sent[0]["body"]
    assert body["personalizations"] == [{"to": [{"email": "qa@mashcal.co.il"}]}]
    assert "real@b.co.il" in body["subject"]
    assert "real@b.co.il" in body["content"][0]["value"]


def test_provider_refusal_is_reported_not_raised(mail_env, sent, monkeypatch, capsys):
    """A 403 from the provider must not take the invite down with it — and the
    reason it gives is logged, since that text is the answer to nearly every
    mail that never arrives."""
    import urllib.error

    def _refuse(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {},
            __import__("io").BytesIO(
                b'{"errors":[{"message":"The from address does not match a verified Sender Identity."}]}'))

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
    mail_env.setenv("SENDGRID_API_KEY", "SG.test-key")
    mail_env.setenv("INVITE_FROM_EMAIL", "no-reply@mashcal.co.il")

    assert cityos_main._send_email("a@b.co.il", "נושא", "<p>שלום</p>") is False
    assert "verified Sender Identity" in capsys.readouterr().out
