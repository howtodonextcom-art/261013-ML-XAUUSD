"""Authentication, session cookie, WebSocket handshake, rate limiting, binding guard (P2 security)."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/gateway"))
sys.path.insert(0, str(ROOT / "services/intelligence"))
from xau_gateway import auth  # noqa: E402

pytestmark = pytest.mark.auth


@pytest.fixture()
def token(tmp_path, monkeypatch):
    monkeypatch.setenv("XAU_TOKEN_FILE", str(tmp_path / "api_token"))
    auth._cached.update(token=None, path=None)
    from xau_gateway import app as appmod
    appmod.AUTH_LIMITER.fails.clear()
    return auth.ensure_token()


@pytest.fixture()
def client(token):
    from fastapi.testclient import TestClient
    from xau_gateway.app import app
    return TestClient(app, base_url="http://127.0.0.1:8765", follow_redirects=False, client=("127.0.0.1", 50000))


def test_token_is_generated_persisted_reused_and_short_ones_are_replaced(tmp_path, monkeypatch):
    f = tmp_path / "t"
    monkeypatch.setenv("XAU_TOKEN_FILE", str(f))
    auth._cached.update(token=None, path=None)
    a = auth.ensure_token()
    assert len(a) >= 40 and f.read_text().strip() == a
    auth._cached.update(token=None, path=None)
    assert auth.ensure_token() == a                                           # reused from the file
    f.write_text("short\n")
    auth._cached.update(token=None, path=None)
    b = auth.ensure_token()
    assert b != "short" and len(b) >= 40
    monkeypatch.setenv("XAU_API_TOKEN", "x" * 30)
    assert auth.ensure_token() == "x" * 30                                    # the environment wins


def test_credential_helpers_are_exact():
    t = "T" * 40
    assert auth.bearer_ok("Bearer " + t, t) and auth.bearer_ok("bearer " + t, t)
    for bad in (None, "", "Bearer", "Bearer " + t[:-1], "Bearer " + t + "x", "Basic " + t, t):
        assert not auth.bearer_ok(bad, t), bad
    sv = auth.session_value(t)
    assert sv != t and t not in sv and "." in sv
    assert auth.cookie_ok(f"a=b; {auth.COOKIE}={sv}; c=d", t) and not auth.cookie_ok(f"{auth.COOKIE}={t}", t) and not auth.cookie_ok("", t) and not auth.cookie_ok(None, t)
    assert not auth.cookie_ok(f"{auth.COOKIE}={sv[:-1]}", t) and not auth.cookie_ok(f"x{auth.COOKIE}={sv}", t)
    assert auth.query_token_ok(t, t) and not auth.query_token_ok(t[:-1], t) and not auth.query_token_ok(None, t) and not auth.query_token_ok("", t)


def test_the_session_cookie_expires_and_dies_with_the_token():
    import time
    t = "T" * 40
    fresh, old = auth.session_value(t), auth.session_value(t, expires=int(time.time()) - 5)
    assert auth.session_ok(fresh, t) and not auth.session_ok(old, t)                       # a stolen cookie stops working at its expiry
    assert not auth.session_ok(fresh, "U" * 40)                                            # replacing the token file invalidates every cookie
    exp, _, sig = fresh.partition(".")
    assert not auth.session_ok(f"{int(exp) + 86400}.{sig}", t)                              # the expiry is part of the signature: it cannot be extended
    assert not auth.session_ok("abc.def", t) and not auth.session_ok("", t) and not auth.session_ok("123", t)


def test_authentication_cannot_be_switched_off_without_an_explicit_loopback_host(monkeypatch):
    monkeypatch.setenv("XAU_AUTH", "off")
    monkeypatch.delenv("XAU_HOST", raising=False)
    assert auth.auth_enabled()                                                             # a gateway started some other way (uvicorn --host 0.0.0.0) keeps authentication
    monkeypatch.setenv("XAU_HOST", "0.0.0.0")
    assert auth.auth_enabled()
    monkeypatch.setenv("XAU_HOST", "127.0.0.1")
    assert not auth.auth_enabled()


def test_rate_limiter_blocks_after_the_limit_and_recovers():
    r = auth.RateLimiter(3, 10.0)
    for i in range(3):
        assert not r.blocked("k", now=i)
        r.fail("k", now=i)
    assert r.blocked("k", now=5) and not r.blocked("other", now=5)
    assert not r.blocked("k", now=20)                                          # the window passed


def test_api_requires_credentials_bearer_works_wrong_bearer_is_counted_then_blocked(client, token):
    assert client.get("/api/intel").status_code == 401
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/candles/M1").status_code == 401
    assert client.get("/api/intel", headers={"authorization": "Bearer " + token}).status_code == 200
    for _ in range(10):
        assert client.get("/api/intel", headers={"authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/intel", headers={"authorization": "Bearer wrong"}).status_code == 429
    assert client.get("/api/intel", headers={"authorization": "Bearer " + token}).status_code == 200      # the owner is never locked out by an attacker's failures


def test_cookie_bootstrap_sets_an_httponly_samesite_cookie_that_is_not_the_token_and_strips_the_url(client, token):
    r = client.get("/")
    assert r.status_code == 401 and token not in r.text
    r = client.get("/?token=" + token)
    assert r.status_code == 303 and r.headers["location"] == "/"
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc
    assert token not in r.headers["set-cookie"] and token not in r.text
    cookie = r.headers["set-cookie"].split(";")[0]
    ok = client.get("/", headers={"cookie": cookie})
    assert ok.status_code == 200 and "Scalping Intelligence" in ok.text
    assert client.get("/api/intel", headers={"cookie": cookie}).status_code == 200
    assert client.get("/api/intel", headers={"cookie": cookie.replace("=", "=0", 1)}).status_code == 401


def test_wrong_query_token_is_refused_and_rate_limited(client, token):
    for _ in range(10):
        assert client.get("/?token=nope").status_code == 401
    assert client.get("/?token=nope").status_code == 429                         # wrong tokens are throttled: guessing is not free
    assert client.get("/?token=" + token).status_code == 303                     # ...but the right token always works: an attacker (or a web page navigating here) cannot lock the owner out


def test_static_assets_stay_public_but_nothing_with_data_does(client):
    assert client.get("/static/vendor/lwc.js").status_code == 200
    assert client.get("/favicon.ico").status_code == 204


def test_host_and_origin_checks_run_before_authentication(client, token):
    assert client.get("/api/intel", headers={"host": "evil.example:8765", "authorization": "Bearer " + token}).status_code == 403
    assert client.get("/api/intel", headers={"origin": "https://evil.example", "authorization": "Bearer " + token}).status_code == 403


def test_websocket_handshake_requires_credentials(client, token):
    from starlette.websockets import WebSocketDisconnect
    H = {"host": "127.0.0.1:8765"}                                             # the TestClient's own default Host is "testserver", which the Host guard refuses
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers=H) as w:                  # allowed host, NO credentials: refused for that reason alone
            w.receive_text()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={**H, "authorization": "Bearer wrong"}) as w:
            w.receive_text()
    cookie = client.get("/?token=" + token).headers["set-cookie"].split(";")[0]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"host": "evil.example:8765", "cookie": cookie}) as w:     # valid cookie, foreign Host: refused
            w.receive_text()
    with client.websocket_connect("/ws", headers={**H, "cookie": cookie}) as w:
        assert '"type": "health"' in w.receive_text()
    with client.websocket_connect("/ws", headers={**H, "authorization": "Bearer " + token}) as w:
        assert '"type": "health"' in w.receive_text()


def test_auth_can_be_switched_off_for_development_only_with_an_explicit_loopback_host(client, monkeypatch):
    monkeypatch.setenv("XAU_AUTH", "off")
    assert client.get("/api/intel").status_code == 401                          # XAU_HOST unset: still authenticated
    monkeypatch.setenv("XAU_HOST", "127.0.0.1")
    assert client.get("/api/intel").status_code == 200


def test_a_non_loopback_binding_without_authentication_refuses_to_start(monkeypatch):
    from xau_gateway import app as appmod
    from xau_gateway.app import app, lifespan
    monkeypatch.setattr(appmod, "LOOP", None)                                  # lifespan() stores the running loop in a global; restore it afterwards
    monkeypatch.setenv("XAU_HOST", "0.0.0.0")
    monkeypatch.setenv("XAU_AUTH", "off")

    async def go():
        async with lifespan(app):
            pass
    with pytest.raises(RuntimeError, match="XAU_AUTH=off"):
        asyncio.run(go())
    monkeypatch.delenv("XAU_HOST")                                                # unset host + XAU_AUTH=off is refused too
    with pytest.raises(RuntimeError, match="XAU_AUTH=off"):
        asyncio.run(go())


def test_private_extra_hosts_are_honoured_only_while_authentication_is_on(monkeypatch):
    from xau_gateway.app import request_allowed
    monkeypatch.setenv("XAU_ALLOWED_HOSTS", "100.64.1.2, mac-tunnel")
    assert request_allowed("100.64.1.2:8765", None) and request_allowed("mac-tunnel:8765", "http://mac-tunnel:8765")
    assert not request_allowed("100.64.1.3:8765", None) and not request_allowed("evil.example", None)
    monkeypatch.setenv("XAU_AUTH", "off")
    monkeypatch.setenv("XAU_HOST", "127.0.0.1")
    assert not request_allowed("100.64.1.2:8765", None)                        # no authentication: loopback names only


# ---------------------------------------------------------------- Level 5.1 verification pass
def test_malformed_session_cookies_never_crash_and_never_authenticate(client, token):
    for bad in (b"xau_session=\xb2.abc", ("xau_session=" + "9" * 5000 + ".x").encode(), b"xau_session=.", b"xau_session=1.", b"xau_session=\xff\xff", b"xau_session=99999999999999.deadbeef"):
        r = client.get("/api/intel", headers={"cookie": bad})        # raw bytes: latin-1 characters are legal in a header (str.isdigit() accepted U+00B2)
        assert r.status_code == 401, (bad[:20], r.status_code)                # a 500 here (the old behaviour) would also leak a traceback into the log
    assert not auth.session_ok("\xb2.abc", "T" * 40) and not auth.session_ok("9" * 5000 + ".x", "T" * 40)


def test_websocket_handshake_failures_are_rate_limited_like_http(client, token):
    from starlette.websockets import WebSocketDisconnect
    from xau_gateway import app as appmod
    for _ in range(10):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"host": "127.0.0.1:8765", "authorization": "Bearer wrong"}) as w:
                w.receive_text()
    assert appmod.AUTH_LIMITER.blocked("127.0.0.1")                           # the shared per-client bucket now throttles wrong tokens everywhere
    assert client.get("/?token=nope").status_code == 429
    assert client.get("/?token=" + token).status_code == 303                   # the owner is still never locked out


def test_a_short_environment_token_is_refused(monkeypatch):
    monkeypatch.setenv("XAU_API_TOKEN", "short")
    with pytest.raises(RuntimeError, match="shorter than 24"):
        auth.ensure_token()


def test_the_access_log_never_records_the_one_time_token():
    import logging
    from xau_gateway.app import _RedactToken
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", "/?token=SECRETVALUE123&x=1", "1.1", 303), None)
    assert _RedactToken().filter(rec) is True
    assert "SECRETVALUE123" not in rec.getMessage() and "token=REDACTED" in rec.getMessage() and "x=1" in rec.getMessage()


def test_pid_alive_treats_wait_failed_as_alive_and_uses_typed_handles():
    import inspect
    from xau_gateway import workers
    src = inspect.getsource(workers.pid_alive)
    assert "argtypes" in src and "0xFFFFFFFF" in src


# ---------------------------------------------------------------- Level 5.2: fail-closed on the REAL peer address
def test_peer_is_loopback_classification():
    for ok in ("127.0.0.1", "127.5.5.5", "::1", "::ffff:127.0.0.1", "127.0.0.1%lo"):
        assert auth.peer_is_loopback(ok), ok
    for bad in (None, "", "testclient", "192.168.1.5", "10.0.0.1", "100.64.1.2", "::ffff:192.168.1.5", "2001:db8::1", "localhost", "127.0.0.1.evil.com"):
        assert not auth.peer_is_loopback(bad), bad


def test_with_authentication_off_a_non_loopback_peer_is_refused_even_with_a_spoofed_loopback_host(token, monkeypatch):
    """XAU_AUTH=off + a stale XAU_HOST=127.0.0.1 + a public bind used to run open. Now the socket's real peer decides."""
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from xau_gateway.app import app
    monkeypatch.setenv("XAU_AUTH", "off")
    monkeypatch.setenv("XAU_HOST", "127.0.0.1")
    remote = TestClient(app, base_url="http://127.0.0.1:8765", client=("192.168.1.50", 40000))        # spoofed Host: 127.0.0.1, remote peer
    assert remote.get("/api/intel").status_code == 403
    assert remote.get("/").status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect("/ws", headers={"host": "127.0.0.1:8765"}) as w:
            w.receive_text()
    local = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 40000))
    assert local.get("/api/intel").status_code == 200
    monkeypatch.delenv("XAU_AUTH")                                                                     # authentication on: a remote peer is judged by its credentials, not refused outright
    assert remote.get("/api/intel").status_code == 401
    assert remote.get("/api/intel", headers={"authorization": "Bearer " + token}).status_code == 200


def test_a_real_gateway_process_bound_publicly_with_auth_off_refuses_a_non_loopback_peer(tmp_path):
    """Real process, real sockets: uvicorn on 0.0.0.0 (lifespan off: no MT5) with the dangerous stale environment. A request from this machine's LAN address
    (a non-loopback PEER) with a spoofed `Host: 127.0.0.1` must get 403; the same request from 127.0.0.1 is served."""
    import os
    import socket
    import subprocess
    import time
    import urllib.error
    import urllib.request
    lan = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        lan = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    if not lan or lan.startswith("127."):
        pytest.skip("no non-loopback network address on this machine")
    with socket.socket() as t:
        t.bind(("127.0.0.1", 0))
        port = t.getsockname()[1]
    env = {**os.environ, "XAU_AUTH": "off", "XAU_HOST": "127.0.0.1", "XAU_TOKEN_FILE": str(tmp_path / "t"),
           "PYTHONPATH": os.pathsep.join([str(ROOT / "services/gateway"), str(ROOT / "services/intelligence")])}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "xau_gateway.app:app", "--host", "0.0.0.0", "--port", str(port), "--lifespan", "off", "--no-access-log"],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 30
        code_local = None
        while time.time() < deadline:
            try:
                code_local = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/intel", timeout=2).status
                break
            except urllib.error.HTTPError as e:
                code_local = e.code
                break
            except OSError:
                time.sleep(0.3)
        assert code_local in (200, 500), code_local                                                      # served to the loopback peer (500 only if app state is missing: lifespan is off)
        req = urllib.request.Request(f"http://{lan}:{port}/api/intel", headers={"Host": f"127.0.0.1:{port}"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 403 and b"loopback" in ei.value.read()
    finally:
        p.kill()
        p.wait(10)
