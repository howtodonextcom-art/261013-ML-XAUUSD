"""Mode B reader: partial lines, headers, truncation, malformed input, identity, and a read-only guarantee for the MQL5 sources."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/gateway"))
from xau_gateway.modeb_reader import ModeBReader, identity_mismatch, parse_line  # noqa: E402

HDR = "#schema=1;symbol=XAUUSD;server=MetaQuotes-Demo;account_ref=abcd1234;digits=2;started_msc=1791925000000\n"


def w(p, s, mode="ab"):
    with open(p, mode) as f:
        f.write(s.encode() if isinstance(s, str) else s)


def test_reads_complete_lines_and_keeps_a_partial_one(tmp_path):
    f = tmp_path / "t.csv"
    r = ModeBReader(f)
    assert r.poll() == []                                         # file missing: no exception, reported
    assert r.last_poll_error == "FileNotFoundError"
    w(f, HDR + "1791925000100,4100.10,4100.50,0.00,0,134\n1791925000200,4100.1")
    t = r.poll(now_ns=5)
    assert [x.time_msc for x in t] == [1791925000100] and t[0].bid == 4100.10 and t[0].flags == 134 and t[0].wall_ns == 5
    assert r.header["server"] == "MetaQuotes-Demo" and r.sessions == 1
    w(f, "1,4100.60,0.00,0,6\r\n")                                # completes the partial line (CRLF tolerated)
    t = r.poll()
    assert len(t) == 1 and t[0].time_msc == 1791925000200 and t[0].bid == 4100.11 and t[0].ask == 4100.60 and t[0].flags == 6 and r.bad_lines == 0


def test_partial_line_completed_later_is_one_tick_not_two(tmp_path):
    f = tmp_path / "t.csv"
    r = ModeBReader(f)
    w(f, HDR + "1791925000100,4100.10,4100.5")
    assert r.poll() == []
    w(f, "0,0.00,0,6\n")
    t = r.poll()
    assert len(t) == 1 and t[0].ask == 4100.50 and t[0].flags == 6 and r.bad_lines == 0


def test_malformed_lines_are_counted_never_raised_never_repaired(tmp_path):
    f = tmp_path / "t.csv"
    r = ModeBReader(f)
    w(f, HDR + "garbage\n1,2,3\n0,4100,4101,0,0,2\n17,nan,4101,0,0,2\n1791925000300,4100.0,4100.4,0.0,0,2\n")
    t = r.poll()
    assert [x.time_msc for x in t] == [1791925000300] and r.bad_lines == 4


def test_truncation_restarts_and_is_reported(tmp_path):
    f = tmp_path / "t.csv"
    r = ModeBReader(f)
    w(f, HDR + "1791925000100,4100.10,4100.50,0.00,0,134\n1791925000200,4100.10,4100.50,0.00,0,134\n")
    assert len(r.poll()) == 2
    w(f, HDR + "1791925009000,4101.00,4101.40,0.00,0,6\n", mode="wb")        # the EA/terminal replaced the file with a shorter one
    t = r.poll()
    assert r.resets == 1 and [x.time_msc for x in t] == [1791925009000]


def test_each_ea_restart_adds_a_header_session(tmp_path):
    f = tmp_path / "t.csv"
    r = ModeBReader(f)
    w(f, HDR + "1791925000100,4100.10,4100.50,0.00,0,134\n" + HDR + "1791925000100,4100.10,4100.50,0.00,0,134\n")
    t = r.poll()
    assert r.sessions == 2 and len(t) == 2                          # the duplicate across sessions is NOT removed here: the consumer's cursor decides


def test_identity_check():
    exp = {"server": "MetaQuotes-Demo", "account_ref": "abcd1234"}
    h = {"symbol": "XAUUSD", "server": "MetaQuotes-Demo", "account_ref": "abcd1234"}
    assert identity_mismatch(h, exp, "XAUUSD") is None
    assert identity_mismatch({}, exp) and "unknown" in identity_mismatch({}, exp)
    assert "server" in identity_mismatch({**h, "server": "FTMO-Demo"}, exp)
    assert "account" in identity_mismatch({**h, "account_ref": "deadbeef"}, exp)
    assert "symbol" in identity_mismatch({**h, "symbol": "EURUSD"}, exp, "XAUUSD")
    assert identity_mismatch({**h, "symbol": "XAUUSD.r"}, exp, "XAUUSD") is None


def test_parse_line_edge_cases():
    assert parse_line("1791925000100,4100.10,4100.50,0.00,0,134", 1) is not None
    for bad in ("", "a,b", "1,2,3,4,5,6,7", "x,1,2,3,4,5", "-5,1,2,3,4,5"):
        assert parse_line(bad, 1) is None, bad


def test_mql5_sources_are_read_only():
    """No MQL5 source in the repository may contain a trading, position, order, network or file-delete call."""
    banned = re.compile(r"\b(OrderSend\w*|OrderCheck|OrderCalc\w*|CTrade|CPositionInfo|CHistoryOrderInfo|COrderInfo|PositionOpen|PositionClose\w*|"
                        r"PositionModify|OrderOpen|OrderModify|OrderDelete|WebRequest|SocketCreate|SocketConnect|FileDelete|FolderDelete|"
                        r"TradeRequest|MqlTradeRequest|trade/Trade\.mqh|Expert\.mqh)\b|Trade\\Trade\.mqh", re.I)
    src = list((ROOT / "mt5").rglob("*.mq5")) + list((ROOT / "mt5").rglob("*.mqh"))
    assert src, "no MQL5 sources found"
    for p in src:
        text = re.sub(r"//.*", "", p.read_text(encoding="utf-8", errors="replace"))                # comments may say 'no order'
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        m = banned.search(text)
        assert m is None, f"{p.name}: forbidden call {m.group(0)}"


def ea_model(ticks, call_points, overlap_ms=2000, page=5000):
    """Python model of XauTickLoggerModeB.OnTick v1.1 (same algorithm): CopyTicks limited to `page` ticks, paginated until a short page; occurrence
    counting skips what was already written. `call_points[i]` = how many source ticks exist when OnTick call i happens."""
    written, state = [], {"msc": ticks[0][0], "cnt": 0}

    def write_page(chunk):
        cur, seen, new_cnt = state["msc"], 0, state["cnt"]
        for t in chunk:
            m = t[0]
            if m < state["msc"]:
                continue
            if m == state["msc"]:
                seen += 1
                if seen <= state["cnt"]:
                    continue
            written.append(t)
            if m != cur:
                cur, new_cnt = m, 1
            else:
                new_cnt += 1
        state["msc"], state["cnt"] = cur, new_cnt

    for n_avail in call_points:
        frm = max(0, state["msc"] - overlap_ms)
        for pages in range(400):
            want = page if pages == 0 else page + state["cnt"]                       # later pages ask for the already-written ticks as extra
            window = [t for t in ticks[:n_avail] if t[0] >= frm][:want]              # CopyTicks(from, count=want)
            if not window:
                break
            write_page(window)
            if len(window) < want:
                break
            frm = state["msc"]
    return written


def test_ea_algorithm_neither_loses_nor_duplicates_ticks_even_with_same_millisecond_ticks_and_batched_calls():
    import random
    rnd = random.Random(7)
    ticks, t = [], 1_791_925_000_000
    for i in range(400):
        t += rnd.choice([0, 0, 1, 5, 40, 300])                    # many ticks share a millisecond
        ticks.append((t, 4100.0 + i * 0.01, 4100.4 + i * 0.01, 134))
    points = sorted(rnd.sample(range(1, 401), 60)) + [400]       # OnTick fires at irregular points, several ticks arrive between calls
    out = ea_model(ticks, points)
    assert out == ticks
    for pg in (3, 7, 50, 399, 5000):                                              # a burst bigger than one page (v1.0 lost the tail beyond 5000 ticks)
        assert ea_model(ticks, points, page=pg) == ticks, pg
    assert ea_model(ticks, [400], page=13) == ticks                            # everything arrives in ONE call
                                                       # nothing skipped, nothing doubled, order kept
    assert len(set(out)) == len(out)


def test_ea_gap_markers_and_suspected_restart_gaps_are_reported_not_hidden(tmp_path):
    f = tmp_path / "t.csv"
    r = ModeBReader(f)
    w(f, HDR + "1791925000100,4100.10,4100.50,0.00,0,134\n#gap;from_msc=1791925000100;reason=page_cap\n")
    w(f, "#schema=1;symbol=XAUUSD;server=MetaQuotes-Demo;account_ref=abcd1234;digits=2;started_msc=1791925060000\n1791925060100,4100.10,4100.50,0.00,0,6\n")
    t = r.poll()
    assert len(t) == 2 and r.sessions == 2
    kinds = [g["kind"] for g in r.gaps]
    assert kinds == ["EA_GAP_MARKER", "SUSPECTED_RESTART_GAP"] and r.gaps[0]["reason"] == "page_cap"
    assert r.header["started_msc"] == "1791925060000"                          # a #gap line must not overwrite the identity header
    assert identity_mismatch(r.header, {"server": "MetaQuotes-Demo", "account_ref": "abcd1234"}, "XAUUSD") is None
