# SOURCE IDENTITY & TERMINAL ISOLATION

The machine runs two MT5 terminals (MetaQuotes-Demo and FTMO). The application only reads from the terminal pinned in `configs/source.json` (git-ignored; `configs/source.example.json` shows the shape).

## Pinned identity
`terminal_path`, `expected.server`, optional `expected.build`, `expected.account_ref` = first 8 hex of SHA-256 of the account number (the number itself is never stored or logged; note 8 hex of a short numeric id is a weak obfuscation, which is why the file is not committed). `scripts/windows/pin_identity.py <terminal64.exe>` prints the block.

## One implementation, three callers
`xau_gateway/identity.verify_identity` is used by the live source, the backfill and `benchmarks/live_vs_history.py`. It checks: terminal install directory equals the configured path's directory, broker server, build (if pinned), account_ref (if pinned). Mismatch => `SOURCE_MISMATCH`, MT5 is shut down and **nothing is collected**; the source never falls back to another terminal. The backfill refuses to run when no server is pinned.

## Evidence
- `tests/integration/test_live_identity.py` (real terminal): wrong server -> `SOURCE_MISMATCH`, 0 ticks; wrong account_ref -> `SOURCE_MISMATCH`, 0 ticks; correct identity -> connected, ticks flow, the status object contains no login.
- Data isolation: manifest rows and parquet paths carry server/symbol; reads are filtered (see STORAGE_RECOVERY).
- Public repository: `configs/source.json`, `data/store`, `.env`, `qa-artifacts/` and `image/` are not committed; secret scan before each push (CLAUDE.md).

## Limits
- `terminal_path` comparison is directory-based; two copies of the same terminal in one directory are impossible, but a portable-mode copy elsewhere with the same server and account would pass the server/account checks and fail only the path check.
- The check runs at connect time. A terminal that logs into another account while connected is detected on the next reconnect, not instantly.
