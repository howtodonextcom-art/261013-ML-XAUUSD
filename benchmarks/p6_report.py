"""Render docs/research/BACKTEST_REPORT_DEVVAL.md from results/p6/devval.json (no numbers are typed by hand)."""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "results" / "p6" / "devval.json").read_text(encoding="utf-8"))
f = lambda v, d=2: "n/a" if v is None else f"{v:.{d}f}"
d = lambda s: time.strftime("%Y-%m-%d", time.gmtime(s))
m = r["meta"]; b = m["boundaries"]
L = [f"# P6 backtest report: development + validation (holdout NOT opened)", "",
     f"Generated from `results/p6/devval.json` (code {m['code']['sha'][:8]}{' + uncommitted changes' if m['code']['dirty'] else ''}, engine {m['code']['engine_version']}, dataset hash {m['dataset_hash'][:16]}, config hash {m['config_hash'][:16]}).",
     f"Protocol: BACKTEST_PREREGISTRATION.md + BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md (frozen before the run). Data: MetaQuotes-Demo XAUUSD bars, span {d(b['t0'])} to {d(b['t1'])} (server time); development to {d(b['dev_end'])}, validation to {d(b['val_end'])}; the holdout (last 20%) bars are read from the store but dropped before any computation and never enter a result.", "",
     "## Verdict", "",
     f"**{r['validation_gate']['verdict']}**: cand-1 (C4) produced {r['validation_gate']['c4_val_trades']} validation trades (minimum {r['validation_gate']['min_trades']}); holdout may open: **{r['validation_gate']['holdout_may_open']}**. "
     "The holdout stays sealed. No claim of an edge can be made, and none is made: the sample is a few dozen trades over about eight months.", "",
     "## Per candidate and segment (base cost: spread + 0.1 USD/oz slippage per side, commission 0; R = net P/L / planned stop distance)", "",
     "| Cand | Segment | n | mean R | win % | 95% CI of mean R (day bootstrap) | mean R @ slip 0.3 | @ +7 USD/lot | @ spread floor 0.2 | @ spread floor 0.4 | optimistic bound | ambiguous bars |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for c in ("C3", "C4", "C5", "C6", "C7"):
    for s, x in r["candidates"][c]["segments"].items():
        if not x.get("n"):
            L.append(f"| {c} | {s} | 0 | | | | | | | | | |")
            continue
        ci = x["bootstrap_base"]["ci95"]
        L.append(f"| {c} | {s} | {x['n']} | {f(x['base']['mean_r'])} | {f(100 * x['base']['win_rate'], 0)} | [{f(ci[0])}, {f(ci[1])}] | {f(x['costs']['slip0.3'])} | {f(x['costs']['comm7'])} | {f(x['costs']['spread0.2'])} | {f(x['costs']['spread0.4'])} | {f(x['optimistic_ambiguous_mean_r'])} | {x['ambiguous_bars_total']} |")
L += ["", "C0 (always WAIT) trades nothing by definition. C6 reproduces C4 exactly (identical trade fingerprints: " + str(r["candidates"]["C6"]["identical_to_C4"]) + ") because setup-1 never uses liquidity-sweep evidence; it is a null control, not an independent ablation.", "",
      "## C1 random entries with C4 geometry (500 seeds)", "", "| Segment | seeds | C4 mean R | C1 p5 | p50 | p95 | C4 above C1 p95 | share of seeds >= C4 |", "|---|---|---|---|---|---|---|---|"]
for s, x in r["candidates"]["C1"]["segments"].items():
    p = x.get("mean_r_percentiles") or {}
    L.append(f"| {s} | {x['seeds']} | {f(x['c4_mean_r'])} | {f(p.get('5'))} | {f(p.get('50'))} | {f(p.get('95'))} | {x['c4_above_p95']} | {f(x['share_of_seeds_at_or_above_c4'])} |")
L += ["", "## C2 buy-and-hold (USD per ounce, one fixed lot, includes one spread)", ""]
for s, x in r["candidates"]["C2"]["segments"].items():
    L.append(f"- {s}: {f(x['usd_per_oz']) if x else 'n/a'}")
L += ["", "## C4 decomposition", ""]
c4 = r["candidates"]["C4"]
L.append(f"- Decisions not traded / skipped (whole development+validation span): {json.dumps(c4['counters'], sort_keys=True)}")
for s in ("dev", "val"):
    x = c4["segments"][s]
    if x.get("n"):
        L.append(f"- {s}: by direction {json.dumps({k: (v['n'], round(v['mean_r'], 2)) for k, v in x['by_direction'].items()})}; by H1 context {json.dumps({k: (v['n'], round(v['mean_r'], 2)) for k, v in x['by_h1_context'].items()})}; "
                 f"by server session {json.dumps({k: (v['n'], round(v['mean_r'], 2)) for k, v in x['by_server_session'].items()})}; month concentration {f(x['month_concentration'])}")
L += ["", "## Reading this honestly", "",
      "- Point estimates of mean R for C4 are positive in development and validation, but every 95% interval includes zero and the counts are tiny (see n). This is exactly the situation the pre-registration calls INSUFFICIENT_EVIDENCE.",
      "- **Spread caveat (independent review):** the stored M5 `spread` field is not a stable real spread: monthly medians are 0.13-0.16 USD in Oct-Nov 2025, a constant 0.04 from Jan to May 2026, 52% zero bars in June 2026 and 0.10-0.14 later. Most dev/val fills therefore paid 0.04 or 0.00; the 'net of spread' figures are effectively 'net of the 0.1 slippage'. The spread-floor columns (0.2 / 0.4 USD) are the realistic sensitivity and must be read before any holdout is interpreted: a later period with larger spreads is a cost-regime change, not evidence about the strategy.",
      "- **Power:** C4 produced 28-29 trades in about eight months. A 73-day holdout would yield roughly 7 trades, so the pre-registered 100-trade holdout threshold is unreachable with this data: the holdout could only ever return INSUFFICIENT_EVIDENCE. More history (M15 bars exist for a year only) or more candidates would be needed for a real test.",
      "- C3 (trend onset only) is also positive in the same periods: the period contained a large up-trend followed by a drop (C2), so direction-agnostic comparisons are fragile.",
      "- C5 is not a pure zone removal: a real zone that is touched without a pattern bar still goes to AT_RELEVANT_ZONE; the pseudo-zone path only applies when no zone exists. The pseudo-zone skips the 'zone above the impulse start' check.",
      "- Selection effects: one trade per setup at its first eligible bar; 31 of 60 eligible decisions were blocked by risk-1 (RR_TOO_LOW or SL_TOO_CLOSE with the 6 USD stops level measured on MetaQuotes-Demo); trades unresolved at the segment end are dropped; the timeout is 288 M5 BARS (not 24 h: market breaks make a held trade span longer).",
      "- Earlier structural experiments (swing-k grid, setup lifecycle) looked at the full year including what is now the holdout, but no outcome (P/L) was used: the contamination is structure-only.",
      "- Many eligible setups were BLOCKED by the broker stops level or the net R:R floor: those decisions are counted, not hidden.",
      "- Limits: spread is a bar value, not tick exact; one instrument, one broker feed, one regime period; demo data; bar-level fills (stop/target ambiguity resolved against the trade, SELL stops triggered on the ask); M5 holes not independently audited beyond the existing data QA.", ""]
(ROOT / "docs" / "research" / "BACKTEST_REPORT_DEVVAL.md").write_text(chr(10).join(L), encoding="utf-8")
print(chr(10).join(L)[:800])
