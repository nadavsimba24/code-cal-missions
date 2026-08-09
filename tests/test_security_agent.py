"""Group 13 — the multi-scanner security agent (scripts/security_agent.py)."""
import importlib.util
import pathlib

_P = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "security_agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("security_agent", _P)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_loads_and_has_remediations():
    m = _load()
    for tid in ("B602", "B608", "B324", "B105"):
        assert tid in m.REMEDIATION and m.REMEDIATION[tid]
    assert set(m.ALL_SCANNERS) == {"sast", "deps", "secrets", "authz"}


def test_auto_fixers_are_safe_and_mechanical():
    m = _load()
    fn, _ = m.auto_fixer("B324")
    assert fn and fn("d = hashlib.md5(x)\n") == "d = hashlib.sha256(x)\n"
    fn, _ = m.auto_fixer("B506")
    assert fn("cfg = yaml.load(f)\n") == "cfg = yaml.safe_load(f)\n"
    fn, _ = m.auto_fixer("B501")
    assert fn("requests.get(u, verify=False)\n") == "requests.get(u, verify=True)\n"


def test_non_mechanical_findings_have_no_auto_fix():
    m = _load()
    for tid in ("B602", "B608", "B110"):
        assert m.auto_fixer(tid)[0] is None


def test_secret_patterns_detect_and_skip_env():
    m = _load()
    # a hardcoded generic secret is caught
    assert any(rx.search('api_key = "s3cr3tValue123"') for _, rx in m.SECRET_PATTERNS)
    # a private-key header is caught
    assert any(rx.search("-----BEGIN RSA PRIVATE KEY-----") for _, rx in m.SECRET_PATTERNS)
    # env reads / placeholders are treated as safe (skipped by _SAFE)
    assert m._SAFE.search('api_key = os.environ.get("X")')
    assert m._SAFE.search('token = process.env.TOKEN')
    assert m._SAFE.search('password = "your_password_here"')


def test_authz_scanner_runs_and_flags_only_mutating():
    m = _load()
    res = m.scan_authz()
    assert isinstance(res, list)
    assert all(f["scanner"] == "authz" and f["severity"] == "MEDIUM" for f in res)
    # the heuristic must never flag an endpoint whose body references a known auth signal
    assert m.AUTH_SIGNALS and "_cap(" in m.AUTH_SIGNALS and "_board_role" in m.AUTH_SIGNALS
