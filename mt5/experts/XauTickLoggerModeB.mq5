//+------------------------------------------------------------------+
//| XauTickLoggerModeB.mq5                                            |
//| READ-ONLY Expert Advisor ("Mode B" capture): on every incoming    |
//| tick it appends every tick not yet written to a CSV in the COMMON |
//| files folder; the Python gateway tails that file. It performs NO  |
//| trading action of any kind: there is no order, position or        |
//| trade-request call, no CTrade include, and no WebRequest/network. |
//| Attach to ONE XAUUSD chart of the MetaQuotes-Demo terminal.       |
//| File: <Common>\Files\xau_modeb_<symbol>.csv                       |
//|   header line:  #schema=1;symbol=..;server=..;account_ref=..;digits=..|
//|   data line:    time_msc,bid,ask,last,volume,flags                |
//| The account number is never written, only the first 8 hex chars   |
//| of SHA-256(account number) (same obfuscation as the Python side). |
//+------------------------------------------------------------------+
#property copyright "xauusd-terminal"
#property version   "1.00"

input int  InpOverlapMs = 2000;   // re-read this much history on each call; duplicates are skipped by occurrence counting

int      g_fh        = INVALID_HANDLE;
string   g_file      = "";
long     g_last_msc  = 0;         // newest time_msc written
int      g_last_cnt  = 0;         // how many ticks with time_msc == g_last_msc were already written
ulong    g_written   = 0;

string AccountRef()
  {
   string txt = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   uchar src[], key[], dst[];
   StringToCharArray(txt, src, 0, StringLen(txt));
   if(CryptEncode(CRYPT_HASH_SHA256, src, key, dst) <= 0) return "";
   return StringFormat("%02x%02x%02x%02x", dst[0], dst[1], dst[2], dst[3]);
  }

int OnInit()
  {
   g_file = "xau_modeb_" + _Symbol + ".csv";
   g_fh = FileOpen(g_file, FILE_WRITE | FILE_READ | FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(g_fh == INVALID_HANDLE) { Print("XauTickLoggerModeB: FileOpen failed err=", GetLastError()); return INIT_FAILED; }
   FileSeek(g_fh, 0, SEEK_END);
   // a new session always starts with its own header so the reader can detect an EA restart (and verify the source identity)
   string h = StringFormat("#schema=1;symbol=%s;server=%s;account_ref=%s;digits=%d;started_msc=%I64d\n", _Symbol, AccountInfoString(ACCOUNT_SERVER), AccountRef(),
                           (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS), (long)TimeCurrent() * 1000);
   FileWriteString(g_fh, h);
   FileFlush(g_fh);
   MqlTick t;
   if(SymbolInfoTick(_Symbol, t)) { g_last_msc = t.time_msc; g_last_cnt = 0; }
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_fh != INVALID_HANDLE) { FileFlush(g_fh); FileClose(g_fh); g_fh = INVALID_HANDLE; }
  }

void OnTick()
  {
   if(g_fh == INVALID_HANDLE) return;
   MqlTick ticks[];
   long from = g_last_msc - InpOverlapMs;
   if(from < 0) from = 0;
   int n = CopyTicks(_Symbol, ticks, COPY_TICKS_ALL, (ulong)from, 5000);
   if(n <= 0) return;
   long cur_msc = g_last_msc;
   int  seen_at_last = 0;            // occurrences of g_last_msc seen while scanning
   int  new_cnt = g_last_cnt;
   for(int i = 0; i < n; i++)
     {
      long m = ticks[i].time_msc;
      if(m < g_last_msc) continue;                         // older than what was written
      if(m == g_last_msc)
        {
         seen_at_last++;
         if(seen_at_last <= g_last_cnt) continue;          // already written (occurrence counting, as the Python Mode A cursor does)
        }
      string line = StringFormat("%I64d,%.*f,%.*f,%.*f,%I64u,%u\n", m, _Digits, ticks[i].bid, _Digits, ticks[i].ask, _Digits, ticks[i].last, ticks[i].volume, ticks[i].flags);
      FileWriteString(g_fh, line);
      g_written++;
      if(m != cur_msc) { cur_msc = m; new_cnt = 1; } else new_cnt++;
     }
   if(cur_msc != g_last_msc) { g_last_msc = cur_msc; g_last_cnt = new_cnt; } else g_last_cnt = new_cnt;
   FileFlush(g_fh);                 // make every tick visible to the reader immediately
  }
