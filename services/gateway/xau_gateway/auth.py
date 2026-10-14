"""Authentication for the local gateway (P2 security). Threat model: docs/architecture/THREAT_MODEL.md.

One shared secret (the API token) lives OUTSIDE git (configs/api_token, or env XAU_API_TOKEN / XAU_TOKEN_FILE). It is accepted as
  - `Authorization: Bearer <token>` (scripts, tests, other tools), or
  - the session cookie `xau_session` (browsers). The cookie value is NOT the token but HMAC(token, "xau-session-v1"); it is set HttpOnly + SameSite=Strict
    by `GET /?token=<token>` which then redirects to `/` so the token never stays in the address bar or the history.
Comparisons are constant time. Failed attempts are rate limited per client address. Nothing here is logged with the secret.
XAU_AUTH=off disables authentication (development on a loopback binding only: the application refuses it for any other binding).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COOKIE = "xau_session"
_lock = threading.Lock()
_cached: dict = {"token": None, "path": None}


def auth_enabled() -> bool:
    return os.environ.get("XAU_AUTH", "on").strip().lower() != "off"


def token_path() -> Path:
    return Path(os.environ.get("XAU_TOKEN_FILE") or ROOT / "configs" / "api_token")


def ensure_token() -> str:
    """The configured token: env first, then the file; created (random, 256 bit) when neither exists. Cached per file path."""
    env = os.environ.get("XAU_API_TOKEN")
    if env:
        return env.strip()
    p = token_path()
    with _lock:
        if _cached["token"] and _cached["path"] == str(p):
            return _cached["token"]
        if p.exists():
            tok = p.read_text(encoding="utf-8").strip()
        else:
            tok = ""
        if len(tok) < 24:                                         # missing or too short to be a secret: replace it
            tok = secrets.token_urlsafe(32)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(tok + "\n", encoding="utf-8")
            try:
                os.chmod(p, 0o600)                               # best effort (no-op semantics on Windows)
            except OSError:
                pass
        _cached.update(token=tok, path=str(p))
        return tok


def session_value(token: str) -> str:
    return hmac.new(token.encode(), b"xau-session-v1", hashlib.sha256).hexdigest()


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def bearer_ok(authorization: str | None, token: str) -> bool:
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    return _eq(authorization[7:].strip(), token)


def cookie_ok(cookie_header: str | None, token: str) -> bool:
    if not cookie_header:
        return False
    for part in cookie_header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and _eq(v, session_value(token)):
            return True
    return False


def credentials_ok(headers, token: str) -> bool:
    """`headers` is any mapping with case-insensitive .get (Starlette Headers)."""
    return bearer_ok(headers.get("authorization"), token) or cookie_ok(headers.get("cookie"), token)


def query_token_ok(candidate: str | None, token: str) -> bool:
    return bool(candidate) and _eq(candidate, token)


class RateLimiter:
    """At most `limit` failed attempts per `window_s` per key; further attempts are refused until the window passes."""

    def __init__(self, limit: int = 10, window_s: float = 60.0):
        self.limit, self.window_s, self.fails, self._l = limit, window_s, {}, threading.Lock()

    def blocked(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._l:
            xs = [t for t in self.fails.get(key, []) if now - t < self.window_s]
            self.fails[key] = xs
            return len(xs) >= self.limit

    def fail(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._l:
            self.fails.setdefault(key, []).append(now)
            if len(self.fails) > 1000:                          # bounded memory
                self.fails = {k: v for k, v in self.fails.items() if v and now - v[-1] < self.window_s}


def is_loopback_host(h: str) -> bool:
    return h.strip().lower() in ("127.0.0.1", "localhost", "::1", "[::1]")
