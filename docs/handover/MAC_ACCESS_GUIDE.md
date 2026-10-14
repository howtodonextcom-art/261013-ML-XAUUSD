# Using the terminal from a MacBook M1

**Status: NOT TESTED on a Mac.** No Mac was available; this guide is a procedure, not evidence.

## What works and what does not
- The MetaTrader5 Python package has no macOS ARM build: MT5 access and the gateway stay on the Windows PC. The Mac is only a **browser client** (and, separately, a research workstation for the committed code and results).
- The gateway binds `127.0.0.1` only and requires a token. It is never exposed to the Internet.

## Recommended: SSH tunnel (keeps the loopback binding)
1. On the Windows PC enable the OpenSSH Server (Settings > Optional features) and create a key-only login for your own user. Do not forward port 8765 on the router.
2. On the Mac: `ssh -N -L 8765:127.0.0.1:8765 <windows-user>@<windows-pc-address>` (keep it open).
3. Open `http://127.0.0.1:8765/?token=<token>` on the Mac (the token is in `configs\api_token` on the PC; transfer it over the SSH session, not by chat or e-mail). The tunnel makes the Windows gateway appear as loopback on the Mac, so no gateway setting changes.

## Alternative: private VPN address (Tailscale / WireGuard)
1. Start the gateway with the VPN address allowed and still authenticated: `.\scripts\windows\run_gateway.ps1 -BindHost <vpn-ip> -AllowedHosts <vpn-ip>`. The gateway refuses a non-loopback bind without authentication and accepts the extra Host only while authentication is on.
2. On the Mac open `http://<vpn-ip>:8765/?token=<token>`.
3. The traffic is plain HTTP inside the VPN: use only a VPN you control; never a coffee-shop LAN, never a port forward.

## After the first session
Report what happened (browser, macOS version, any layout problem, drawing tools with a trackpad: touch gestures are untested) and update docs/product/PRODUCT_ACCEPTANCE_MATRIX.md. Until then Mac is NOT TESTED.

## Never
Do not open the gateway to the Internet; do not disable authentication; do not share the token or a screenshot containing it.
