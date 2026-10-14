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

bool DumpTf(const ENUM_TIMEFRAMES tf, const string name)
  {
   int h20  = iMA(_Symbol, tf, 20,  0, MODE_EMA, PRICE_CLOSE);
   int h50  = iMA(_Symbol, tf, 50,  0, MODE_EMA, PRICE_CLOSE);
   int h100 = iMA(_Symbol, tf, 100, 0, MODE_EMA, PRICE_CLOSE);
   int h200 = iMA(_Symbol, tf, 200, 0, MODE_EMA, PRICE_CLOSE);
   int hrsi = iRSI(_Symbol, tf, 14, PRICE_CLOSE);
   int hatr = iATR(_Symbol, tf, 14);
   int hmac = iMACD(_Symbol, tf, 12, 26, 9, PRICE_CLOSE);
   int hs[] = {h20, h50, h100, h200, hrsi, hatr, hmac};
   for(int i = 0; i < ArraySize(hs); i++)
      if(hs[i] == INVALID_HANDLE) { Print("indicator handle failed for ", name); return false; }

   for(int w = 0; w < 100; w++)   // wait until every indicator is fully calculated
     {
      bool ok = true;
      for(int i = 0; i < ArraySize(hs); i++)
         if(BarsCalculated(hs[i]) < InpBars + 300) ok = false;
      if(ok) break;
      Sleep(100);
     }

   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, tf, 1, InpBars, r);          // start at 1: closed bars only
   if(n <= 0) { Print("CopyRates failed for ", name); return false; }
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
   for(int i = 0; i < ArraySize(hs); i++) IndicatorRelease(hs[i]);
   PrintFormat("DumpIndicators: %s %s wrote %d bars", _Symbol, name, n);
   return true;
  }

void OnStart()
  {
   DumpTf(PERIOD_M15, "M15");
   DumpTf(PERIOD_H1,  "H1");
   DumpTf(PERIOD_H4,  "H4");
   Alert("DumpIndicators finished: see the Experts log and Terminal\\Common\\Files");
  }
