//+------------------------------------------------------------------+
//| DumpIndicators.mq5                                                |
//| READ-ONLY script: writes closed-bar OHLC and MT5's own indicator  |
//| values (iMA EMA 20/50/100/200, iRSI 14, iATR 14, iMACD 12/26/9)   |
//| to a CSV in the COMMON files folder, so Python can compare its    |
//| implementation with MetaTrader's. No trading function is used.    |
//| Usage: drag onto an XAUUSD chart once; then run                   |
//|   python benchmarks/mt5_indicator_parity.py                       |
//+------------------------------------------------------------------+
#property copyright "xauusd-terminal"
#property version   "1.00"
#property script_show_inputs

input int InpBars = 3000;   // closed bars per timeframe (the forming bar is skipped)

string AccountRef()   // first 8 hex of SHA-256(account number): same obfuscation as the Python side; the number itself is never written
  {
   string txt = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   uchar src[], key[], dst[];
   StringToCharArray(txt, src, 0, StringLen(txt));
   if(CryptEncode(CRYPT_HASH_SHA256, src, key, dst) <= 0) return "";
   return StringFormat("%02x%02x%02x%02x", dst[0], dst[1], dst[2], dst[3]);
  }

void WriteMeta(const string name, const int n, const long first_t, const long last_t)
  {
   int m = FileOpen("xau_ind_" + _Symbol + "_" + name + ".meta", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(m == INVALID_HANDLE) { Print("meta FileOpen failed err=", GetLastError()); return; }
   FileWriteString(m, "schema=1\n");
   FileWriteString(m, "symbol=" + _Symbol + "\n");
   FileWriteString(m, "timeframe=" + name + "\n");
   FileWriteString(m, "server=" + AccountInfoString(ACCOUNT_SERVER) + "\n");
   FileWriteString(m, "account_ref=" + AccountRef() + "\n");
   FileWriteString(m, "terminal_path=" + TerminalInfoString(TERMINAL_PATH) + "\n");
   FileWriteString(m, "build=" + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)) + "\n");
   FileWriteString(m, "bars=" + IntegerToString(n) + "\n");
   FileWriteString(m, "first_time=" + IntegerToString(first_t) + "\n");
   FileWriteString(m, "last_time=" + IntegerToString(last_t) + "\n");
   FileWriteString(m, "dump_utc=" + IntegerToString((long)TimeGMT()) + "\n");
   FileWriteString(m, "dump_server_time=" + IntegerToString((long)TimeCurrent()) + "\n");
   FileWriteString(m, "digits=" + IntegerToString(_Digits) + "\n");
   FileClose(m);
  }

bool DumpTfBody(const ENUM_TIMEFRAMES tf, const string name, int &hs[])
  {
   int h20  = iMA(_Symbol, tf, 20,  0, MODE_EMA, PRICE_CLOSE);
   int h50  = iMA(_Symbol, tf, 50,  0, MODE_EMA, PRICE_CLOSE);
   int h100 = iMA(_Symbol, tf, 100, 0, MODE_EMA, PRICE_CLOSE);
   int h200 = iMA(_Symbol, tf, 200, 0, MODE_EMA, PRICE_CLOSE);
   int hrsi = iRSI(_Symbol, tf, 14, PRICE_CLOSE);
   int hatr = iATR(_Symbol, tf, 14);
   int hmac = iMACD(_Symbol, tf, 12, 26, 9, PRICE_CLOSE);
   ArrayResize(hs, 7);                                      // the caller releases every handle on every exit path
   hs[0] = h20; hs[1] = h50; hs[2] = h100; hs[3] = h200; hs[4] = hrsi; hs[5] = hatr; hs[6] = hmac;
   for(int i = 0; i < ArraySize(hs); i++)
      if(hs[i] == INVALID_HANDLE) { Print("indicator handle failed for ", name); return false; }

   bool ready = false;
   for(int w = 0; w < 200 && !ready; w++)   // wait (up to 20 s) until every indicator is fully calculated
     {
      ready = true;
      for(int i = 0; i < ArraySize(hs); i++)
         if(BarsCalculated(hs[i]) < InpBars + 300) ready = false;
      if(!ready) Sleep(100);
     }
   if(!ready) { Print("indicators not fully calculated for ", name, ": scroll the chart back / retry"); return false; }

   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, tf, 1, InpBars, r);          // start at 1: closed bars only
   if(n <= 0) { Print("CopyRates failed for ", name); return false; }
   if(n < InpBars - 50) { PrintFormat("only %d of %d bars available for %s: refusing to write a dump too short for the parity verdict", n, InpBars, name); return false; }
   double e20[], e50[], e100[], e200[], rs[], at[], mm[], ms[];
   ArraySetAsSeries(e20, false); ArraySetAsSeries(e50, false); ArraySetAsSeries(e100, false); ArraySetAsSeries(e200, false);
   ArraySetAsSeries(rs, false);  ArraySetAsSeries(at, false);  ArraySetAsSeries(mm, false);   ArraySetAsSeries(ms, false);
   if(CopyBuffer(h20, 0, 1, n, e20) != n || CopyBuffer(h50, 0, 1, n, e50) != n || CopyBuffer(h100, 0, 1, n, e100) != n ||
      CopyBuffer(h200, 0, 1, n, e200) != n || CopyBuffer(hrsi, 0, 1, n, rs) != n || CopyBuffer(hatr, 0, 1, n, at) != n ||
      CopyBuffer(hmac, 0, 1, n, mm) != n || CopyBuffer(hmac, 1, 1, n, ms) != n)
     { Print("CopyBuffer failed for ", name, " err=", GetLastError()); return false; }

   int f = FileOpen("xau_ind_" + _Symbol + "_" + name + ".csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(f == INVALID_HANDLE) { Print("FileOpen failed err=", GetLastError()); return false; }
   FileWrite(f, "time", "open", "high", "low", "close", "ema20", "ema50", "ema100", "ema200", "rsi14", "atr14", "macd", "signal");
   for(int i = 0; i < n; i++)
      FileWrite(f, (long)r[i].time, DoubleToString(r[i].open, _Digits), DoubleToString(r[i].high, _Digits),
                DoubleToString(r[i].low, _Digits), DoubleToString(r[i].close, _Digits),
                DoubleToString(e20[i], 8), DoubleToString(e50[i], 8), DoubleToString(e100[i], 8), DoubleToString(e200[i], 8),
                DoubleToString(rs[i], 8), DoubleToString(at[i], 8), DoubleToString(mm[i], 8), DoubleToString(ms[i], 8));
   FileClose(f);
   WriteMeta(name, n, (long)r[0].time, (long)r[n - 1].time);
   PrintFormat("DumpIndicators: %s %s wrote %d bars", _Symbol, name, n);
   return true;
  }

bool DumpTf(const ENUM_TIMEFRAMES tf, const string name)
  {
   int hs[];
   bool ok = DumpTfBody(tf, name, hs);
   for(int i = 0; i < ArraySize(hs); i++)
      if(hs[i] != INVALID_HANDLE) IndicatorRelease(hs[i]);   // released on success AND on every early return
   return ok;
  }

void OnStart()
  {
   DumpTf(PERIOD_M15, "M15");
   DumpTf(PERIOD_H1,  "H1");
   DumpTf(PERIOD_H4,  "H4");
   Alert("DumpIndicators finished: see the Experts log and Terminal\\Common\\Files");
  }
