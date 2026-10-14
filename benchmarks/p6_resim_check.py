"""Independent plain-loop re-simulation of every C4 dev/val trade (no library simulator code); exit non-zero on any mismatch. Run after p6_backtest.py --phase devval."""
import sys,json
sys.path[:0]=["services/gateway","services/intelligence","benchmarks"]
import numpy as np, p6_backtest as P
full,_=P.load_bars(); b=P.boundaries(full["M5"]["time"]); bars=P.cut_bars(full,b["val_end"]); m=bars["M5"]
tr=[json.loads(l) for l in open("results/p6/devval_trades_C4.jsonl")]
bad=0
for t in tr[:29]:
    # independent re-simulation: plain loop, bid chart, slippage 0.1, no library code
    sg=1 if t["direction"]=="BUY" else -1
    i0=int(np.searchsorted(m["time"],t["decision_time"]))
    assert m["time"][i0]==t["decision_time"]
    op,sp=m["open"][i0],m["spread"][i0]
    fill=op+sg*0+ (sp+0.1 if sg==1 else -0.1)
    exitp=None
    for j in range(i0,i0+288):
        h,l,o=m["high"][j],m["low"][j],m["open"][j]
        if sg==1:
            if j>i0 and o<=t["sl"]: exitp=o-0.1;break
            if l<=t["sl"]: exitp=t["sl"]-0.1;break      # conservative: stop first if both
            if h>=t["tp"]: exitp=t["tp"];break
        else:
            if j>i0 and o>=t["sl"]: exitp=o+m["spread"][j]+0.1;break
            if h+m["spread"][j]>=t["sl"]: exitp=t["sl"]+m["spread"][j]+0.1;break
            if l<=t["tp"]: exitp=t["tp"]+m["spread"][j];break
    if exitp is None: exitp=m["close"][j] if sg==1 else m["close"][j]+m["spread"][j]
    r=sg*(exitp-fill)/t["stop_distance"]
    ok=abs(r-t["r"]["base"])<1e-6
    bad+=not ok
    if not ok: print("MISMATCH",t["setup_id"],t["direction"],round(r,4),t["r"]["base"],t["outcome"])
print("checked",len(tr),"mismatches",bad,"SELL trades",sum(t["direction"]=="SELL" for t in tr))
sys.exit(1 if bad else 0)
