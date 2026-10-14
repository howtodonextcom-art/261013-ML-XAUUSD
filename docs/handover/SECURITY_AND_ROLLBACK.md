# Security summary and rollback

Full analysis: docs/architecture/THREAT_MODEL.md. This page is the operator summary.

## Controls in place (all with tests)
- No order path: no `order_send` / `OrderSend` / `CTrade` / position or trade-request call in any Python or MQL5 source (static tests over every file, mutation-checked). The EA only writes a CSV.
- Loopback binding by default; token authentication on every HTTP route (except `/static` and the favicon) and on the WebSocket handshake; HttpOnly SameSite=Strict session cookie that expires after 7 days and dies when the token file is replaced; wrong tokens are throttled (the correct token always works); Host and Origin allow-list (cross-site pages and DNS rebinding are refused).
- **Fail-closed without authentication**: with `XAU_AUTH=off` the gateway serves only loopback PEERS (the socket's real address), whatever the bind or `XAU_HOST` say (real-process test). `XAU_AUTH=off` also refuses to start without an explicit loopback `XAU_HOST`.
- Privacy mode (default): no lot is published and the plan is sized on a reference account, so the public output does not depend on your real equity or margin (tested over price paths and account sizes). `XAU_REVEAL_SIZE=1` is an explicit start-up choice that publishes the lot and then leaks equity to well under 1%.
- The token is never logged (access-log redaction), never in a redirect, never in git. The account number is never written; only a short hash is kept in `configs\source.json` (a 32-bit hash is brute-forceable: keep that file private).
- The heavy analysis runs in a worker process that is killed on timeout and ends itself if the gateway dies.

## Residual risks
Same-user malware can read the token file and the MT5 terminal; plain HTTP (use a tunnel or private VPN); the binding is declared by the start script, so start only with `run_gateway.ps1`; no TLS, no per-user accounts, no audit log; a hash of the account number exists in a private file.

## Rotate the token
Stop the gateway, delete `configs\api_token`, start it, use the new URL. Do this whenever the token was pasted anywhere.

## Roll back a release
1. `git log --oneline` and pick the last good commit. Releases are plain commits on `main` (no feature branches); tag a known-good one first: `git tag known-good <sha>`.
2. Preferred: `git revert <bad-sha>` (keeps history). Emergency only on your own machine: `git checkout <good-sha> -- services apps tests` and restart the gateway.
3. Data is not part of the code: `data\store` is untouched by a code rollback. If a bad run damaged the store, restore the last backup (WINDOWS_RUNBOOK.md) and run `data_qa.py`.
4. Research results (`results\`) are committed with the code SHA and dataset hash that produced them; never delete `results\p6\holdout_*` or edit the frozen pre-registrations.
5. Never force-push; never change the remote; commit with the single identity required by CLAUDE.md.

## Backing up the V2 forward evidence log
`data\shadow\v2_events.jsonl` is the only record of what the V2 shadow observed live; it cannot be rebuilt (history re-derived later is hindsight and is excluded by design). Back it up regularly (at least weekly) and before any upgrade:
```powershell
.\scripts\windows\backup_forward_log.ps1                 # to data\backup (git-ignored)
.\scripts\windows\backup_forward_log.ps1 -Destination D:\xau-backup   # another disk
```
Each copy is timestamped and its SHA-256 is appended to `MANIFEST.sha256`. To restore, stop the gateway, copy the chosen backup over `data\shadow\v2_events.jsonl`, start the gateway (it reloads the logged event ids and will not duplicate). Never edit a line by hand: the evaluator reports unreadable lines and repairs the known legacy SELL format on read only (docs/research/M1_ENTRY_V2_AMENDMENTS.md, A1).
