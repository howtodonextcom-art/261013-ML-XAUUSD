# Threat model: local desktop terminal (security P2)

Scope: the gateway (FastAPI, one process on the Windows trading PC), its dashboard, the MT5 terminal it reads, the local data store. Not a multi-user service.

## Assets
1. Account information: equity, free margin (memory only), the account_ref hash, broker/server names.
2. The research decision stream (BUY/SELL/WAIT/BLOCKED, levels, size): sensitive because size and affordability verdicts bound the account size.
3. Local files: `configs/source.json`, `configs/api_token`, `data/store` (private, git-ignored).
4. Integrity of the data and of what the UI displays (a forged or stale decision on screen).
5. The MT5 account itself: must be unreachable from this software (read-only; no order function exists; tests enforce it).

## Actors and what is defended
| Actor | Capability | Control | Residual risk |
|---|---|---|---|
| Malicious web page in the user's browser | cross-origin fetch / WebSocket to 127.0.0.1, DNS rebinding | Host allow-list (exact loopback names), Origin must be loopback AND same port, SameSite=Strict HttpOnly cookie, authentication on HTTP and on the WebSocket handshake | none known; CSRF is moot: the API has no state-changing endpoint (GET/WS only) |
| Another local OS user | connect to 127.0.0.1:8765 | token required (`configs/api_token`, mode 0600 where the OS honours it) | the file is readable by the same Windows user and administrators |
| Another process of the same user | read the token file, read process memory | none (same trust domain) | accepted: it could equally read the MT5 terminal; do not run untrusted software on the trading PC |
| LAN attacker | reach the port | default bind is loopback only; a non-loopback bind refuses to start without authentication; extra Host names only with authentication (`XAU_ALLOWED_HOSTS`) | plain HTTP: a LAN sniffer sees the cookie/token; use an SSH tunnel or a private VPN, never an untrusted LAN, never the Internet |
| Brute force of the token | guess | 256-bit random token; constant-time comparison; wrong tokens throttled (10 per minute per client, then 429) while the right token always works (an attacker or a web page cannot lock the owner out); session cookie = expiring HMAC (7 days), dies when the token file is replaced; no access log (it would record the one-time query token) | per-client keying only; cookies are not port-isolated by browsers: another local web app on `localhost` receives `xau_session` |
| Observer of the decision stream (authenticated) | infer equity/free margin | privacy mode (default): NO lot is published AND the plan is sized on a hypothetical reference account, so the public decision does not depend on the real account at all (byte-identical for 7 accounts including a 52 USD one and one with no free margin, over a 60-step price path); reasons are constant strings | none known in privacy mode; `XAU_REVEAL_SIZE=1` is an explicit operator decision: it sizes on the live account, publishes the lot and then leaks the account to well under 1% (tested) |
| Log/error readers | read logs, exceptions | exception TYPE only in payloads; the token and account number never logged; account_ref is an 8-hex hash | the hash of a login is brute-forceable for small account-number spaces: do not publish `configs/source.json` |
| Supply chain | compromised dependency | pinned vendor file for the chart library (checked in); Python deps from the venv | not audited |

## Decisions
- Lot visibility options evaluated: (A) hide by default and reveal only to an authenticated owner; (B) show a coarse bucket. B was rejected by analysis: any monotone function of size leaks at its flip points (an observer sees the loss distance and finds the exact threshold at which the bucket changes); randomised thresholds only add noise that averages out over many setups. A was chosen, combined with mandatory authentication; the reveal switch is a start-up environment variable, never a per-request option, so an attacker who obtains a session still cannot ask for the size.
- Authentication is ON by default even on loopback (defence against other users and cross-site abuse); `XAU_AUTH=off` is honoured only when `XAU_HOST` explicitly names a loopback address (set by `run_gateway.ps1`); a gateway started any other way keeps authentication and refuses `XAU_AUTH=off`.
- MacBook M1 access: SSH tunnel to the loopback binding (recommended), or a private VPN address added with `-AllowedHosts`. NOT TESTED on a Mac.

## Accepted residual risks (review round 8)
- The binding is declared by `XAU_HOST` (set by `run_gateway.ps1`), not observed: a stale `XAU_AUTH=off` in the environment combined with a manual `uvicorn --host 0.0.0.0` would run open. Start the gateway only with the script; never export `XAU_AUTH=off`.
- `open_dashboard.ps1` puts the one-time token on a process command line for a moment (same-user trust domain).
- Drawings live in browser localStorage (two tabs: last writer wins).

## Not covered
TLS, per-user accounts, audit log, token rotation UI, protection against malware running as the same user, hardening of the MT5 terminal itself.
