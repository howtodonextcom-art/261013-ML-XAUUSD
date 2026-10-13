# MASTER PROMPT V4.1
# XAU/USD UNIFIED TRADING INTELLIGENCE
## CONTINUE IMPLEMENTATION FROM COMPLETED PHASE 0 & FIRST VERTICAL SLICE

### ROLE & EXECUTION AUTHORITY

Bạn là Principal Quantitative Trading Architect, Senior MetaTrader 5 Engineer, Low-Latency Data Systems Engineer, Machine Learning Research Scientist, Backend/Frontend Architect và Independent QA Auditor.

Hãy trực tiếp tiếp tục xây dựng dự án XAU/USD Trading Intelligence đang tồn tại trong workspace.

KHÔNG tạo dự án mới.

KHÔNG làm lại những thành phần đã hoạt động nếu không có bằng chứng cần sửa.

KHÔNG dừng ở việc viết tài liệu hoặc đề xuất kiến trúc.

Hãy đọc mã nguồn, kiểm tra hệ thống, sửa lỗi, triển khai các module còn thiếu, chạy test, thực hiện benchmark và cung cấp báo cáo kết quả có bằng chứng.

Ngôn ngữ báo cáo: tiếng Việt.

Ngôn ngữ code: phù hợp với kiến trúc dự án, sử dụng typing nghiêm ngặt.

## 0. VERIFIED PROJECT CONTEXT FROM PRIOR REPORT

Workspace dự kiến:

`Z:\Coding\261013-ML-XAUUSD`

Môi trường chính:

- Windows 11.
- MetaTrader 5 của MetaQuotes Ltd.
- Python 3.14 với MetaTrader5 package đã chạy thành công.
- FastAPI WebSocket gateway.
- Chrome dashboard.
- MetaQuotes-Demo XAUUSD.
- Có terminal FTMO khác trên cùng máy.
- Dashboard local tại 127.0.0.1:8765.

Theo báo cáo Phase 0:

- Kết nối MT5: đã chạy.
- Mode A: MT5 Python tick polling đã chạy.
- M1/M5/M15/H1/H4 candle aggregation đã có.
- Dashboard live đã có.
- 238/240 M1 bars khớp MT5 hoàn toàn.
- Hai bar có sai lệch chưa xác định nguyên nhân.
- Gateway latency p50 khoảng 7,8 ms.
- 11 unit tests đã PASS.
- Read-only đã có kiểm tra sơ bộ.
- Mode B chưa triển khai.
- Historical backfill chưa có.
- Tick persistence chưa có.
- Unified Rulebook V3 chưa triển khai.
- Risk Engine chưa có.
- Replay/Backtest chưa có.
- ML Shadow chưa có.
- MacBook M1 chưa được kiểm thử.

Đây là báo cáo trước đó, KHÔNG phải trạng thái mà bạn được phép mặc định là đã xác minh.

Đầu tiên hãy kiểm tra mã nguồn và test lại các kết quả liên quan.

Đọc:

- README.md.
- docs/architecture/ENVIRONMENT_AUDIT.md.
- docs/architecture/ARCHITECTURE_DECISION.md.
- docs/architecture/CONNECTIVITY_MATRIX.md.
- docs/qa/KNOWN_LIMITATIONS.md.
- Các source files, configs, tests và Git history hiện hành.

Nếu đường dẫn hoặc tài liệu không tồn tại, ghi nhận chính xác và tiếp tục theo mã nguồn tìm được.

Không giả định một baseline V1.1.0 của dự án khác đang tồn tại trong repository này.

---

# 1. CRITICAL NON-NEGOTIABLE REQUIREMENTS

## 1.1. An toàn giao dịch

Toàn bộ phiên bản hiện tại phải là:

READ_ONLY + SHADOW + PAPER_SIMULATION.

Không gọi:

- mt5.order_send.
- MQL5 OrderSend.
- MQL5 OrderSendAsync.
- Các wrapper gửi, sửa, hủy lệnh thật.
- Endpoint có khả năng thay đổi vị thế.
- Bất kỳ cơ chế gián tiếp nào gửi trade request.

Cho phép đọc thông tin symbol, account và dữ liệu thị trường phục vụ mô phỏng.

`trade_allowed=False` từ terminal không được coi là cơ chế bảo vệ duy nhất.

Tách lớp kết nối dữ liệu khỏi trading execution bằng interface và quyền hạn rõ ràng.

Kiểm thử static analysis, dependency boundary và runtime behavior.

Không gửi lệnh thử lên MetaQuotes-Demo chỉ để xác minh an toàn.

## 1.2. Terminal isolation

Máy có MetaQuotes-Demo và FTMO.

Bắt buộc:

- Sử dụng đường dẫn terminal cụ thể.
- Xác minh terminal executable/path.
- Xác minh broker server.
- Xác minh account identity nội bộ.
- Xác minh symbol.
- Xác minh terminal build.
- Xác minh data source trước mỗi phiên kết nối.

Không log đầy đủ account ID, password hoặc secret.

Không chuyển sang FTMO khi MetaQuotes-Demo mất kết nối.

Nếu terminal identity khác cấu hình đã chốt, chuyển sang `SOURCE_MISMATCH` và dừng thu thập từ nguồn không mong muốn.

## 1.3. Đúng dữ liệu hơn nhanh dữ liệu

Ưu tiên:

DATA INTEGRITY > SAFETY > CAUSAL CORRECTNESS > LATENCY > STRATEGY > UI.

Không loại bỏ tick, tự tạo bar hay sửa dữ liệu để đạt KPI.

Không báo độ trễ end-to-end khi mới đo một đoạn trong gateway.

Không tuyên bố hệ thống profitable khi chưa có backtest và out-of-sample evidence.

---

# 2. PHASE 1A: ROOT CAUSE INVESTIGATION FOR M1 BAR MISMATCH

Đây là nhiệm vụ P0 đầu tiên.

Báo cáo có hai bar lệch trong 240 bar.

Không chấp nhận giải thích chung chung kiểu "do polling latency".

## 2.1. Trace hai bar lệch

Truy xuất:

- Symbol/server.
- Bar open timestamp UTC.
- Thời gian hiển thị phía server.
- MT5 historical OHLCV.
- Local candle OHLCV.
- Tất cả tick liên quan.
- time_msc.
- Bid/Ask.
- flags.
- Polling batch.
- Cursor trước/sau mỗi batch.
- Thời điểm gateway nhận.
- Reconnect/log nếu có.

Tạo per-bar forensic report:

- OHLC delta.
- Tick volume delta.
- Tick count.
- BID-change count.
- ASK-only count.
- Boundary tick count.
- Duplicate timestamp count.
- Missing/recovered ticks.
- Cursor pagination evidence.

## 2.2. Những nguyên nhân phải kiểm tra

A. Cursor increment làm mất các tick cùng mili giây.

B. Trùng timestamp nhưng tick thực sự khác nhau.

C. Dedupe làm mất những tick hợp lệ có thông tin giống nhau.

D. Batch size không đủ khi tick rate tăng.

E. Pagination/overlap xử lý sai.

F. Tick nằm ở ranh giới chuyển phút.

G. Sai timezone hoặc bucket timestamp.

H. OHLC dựng từ Bid trong khi dữ liệu gốc có convention khác.

I. Gateway bắt đầu thu thập giữa nến.

J. Tick history của MT5 khác dữ liệu live đã thu nhận.

K. Tick_volume được đếm không tương thích MT5.

L. Restart hoặc mất dữ liệu nhưng không ghi nhận.

M. Rollover, session boundary hoặc lịch sử bị điều chỉnh.

Không kết luận một nguyên nhân nếu không có log hoặc phép đối chiếu chứng minh.

## 2.3. Cursor correctness

Triển khai cursor/pagination đảm bảo không bỏ sót khi nhiều tick có cùng time_msc.

Không dùng duy nhất quy tắc:

`next_cursor = last_time_msc + 1`

trừ khi đã chứng minh không thể mất tick.

Nghiên cứu overlap window, page reconciliation, occurrence counts, payload fingerprint và checkpoint.

Không mặc định fingerprint giống nhau là cùng một tick nếu nguồn không có unique tick ID.

Nếu không thể phân biệt những tick thực sự giống hệt nhau tại cùng timestamp, phải công bố giới hạn dữ liệu thay vì tuyên bố exact-once.

Kiểm thử synthetic fixtures cho:

- 2, 10 và 100 tick cùng time_msc.
- Tick cùng timestamp nhưng khác Bid/Ask.
- Tick payload giống nhau hoàn toàn.
- Batch boundary.
- Pagination retry.
- Process restart.

## 2.4. Acceptance Gate

Chỉ đánh dấu M1 parity được chứng nhận khi:

- Toàn bộ eligible completed bars trong tập đối chiếu chính khớp theo tolerance chính thức.
- Mọi bar bị loại khỏi tập đối chiếu có reason code và bằng chứng.
- Hai bar lệch ban đầu có root cause hoặc được cách ly như lỗi chưa giải thích.
- Có regression tests tái tạo lỗi.
- Không có silent loss.

Nếu chưa đạt, tiếp tục xây dựng các module độc lập nhưng không dùng dữ liệu lỗi để công bố kết quả chiến lược đã kiểm chứng.

Deliverable:

`docs/qa/M1_BAR_MISMATCH_RCA.md`

---

# 3. PHASE 1B: HISTORICAL BACKFILL & TICK PERSISTENCE

## 3.1. Historical Data Ingestion

Triển khai các chức năng:

- Backfill MT5 M1 rates.
- Backfill historical ticks theo khoảng.
- Incremental update.
- Resume từ checkpoint.
- Chunked fetching.
- Rate limiting.
- Data validation.
- Progress reporting.

Đọc giới hạn dữ liệu thực tế từ terminal.

Không tự động tải toàn bộ lịch sử nhiều năm ngay trong lần chạy đầu tiên.

Mặc định sử dụng một khoảng dữ liệu nhỏ để kiểm thử pipeline trước.

Chỉ mở rộng backfill sau khi ước lượng được dung lượng, tốc độ và tính đầy đủ.

## 3.2. Canonical Storage

Ưu tiên nghiên cứu:

- Parquet cho historical ticks/rates.
- SQLite WAL cho metadata, dataset manifest và setup events.
- Raw tick partition theo date/source/symbol.
- Cơ chế ghi atomic.
- Checksums.
- Schema version.

Lưu tối thiểu:

source_id,
terminal identity reference,
server,
symbol,
time_msc,
bid,
ask,
last,
flags,
volume,
received_at,
quality_flags,
dataset_version.

Không xóa dữ liệu gốc sau khi tạo candles.

## 3.3. Source of Truth

Phân biệt:

1. Historical MT5 bars.
2. Historical MT5 ticks.
3. Locally captured live ticks.
4. Reconstructed candles.
5. Quality-controlled candles.

Không trộn nguồn khác broker/server mà không ghi provenance.

Không thay thế một vùng dữ liệu thiếu bằng bar nhân tạo.

## 3.4. Data Quality

Phát hiện:

- Invalid Bid/Ask.
- Empty/missing data.
- Duplicate-looking ticks.
- Out-of-order data.
- Tick gaps.
- Candle mismatch.
- Suspicious spike.
- Abnormal spread.
- Session boundary.
- Rollover anomalies.
- Unexpected timezone shift.
- Incomplete current candle.

Đặc biệt rà soát các bar ở vùng rollover có đặc điểm bất thường:

- Spread bằng 0.
- Tick volume phi lý so với phân phối lịch sử.
- OHLC bất thường.
- OHLC trùng khớp đáng ngờ với phiên kế tiếp.

Không kết luận bar giả chỉ từ một đặc điểm.

Tạo quarantine, báo cáo và chính sách nghiên cứu riêng. Không âm thầm xóa dữ liệu.

## 3.5. Acceptance

- Restart không làm mất checkpoint.
- Re-running backfill không nhân đôi dữ liệu.
- Data manifest chính xác.
- Không có silent corruption.
- Historical bar count được đối chiếu.
- Có data quality report.
- Có test dữ liệu rollover và timezone.
- Có thể truy xuất dữ liệu làm đầu vào cho deterministic replay.

Deliverables:

- HISTORICAL_DATA_SPEC.md.
- BACKFILL_REPORT.md.
- DATA_QUALITY_REPORT.md.
- STORAGE_RECOVERY.md.

---

# 4. PHASE 2: MODE B MQL5 TICK BRIDGE

Xây dựng Mode B như một phương án kết nối cạnh tranh với Mode A.

Không mặc định Mode B nhanh hơn.

## 4.1. Read-only EA

Tạo:

`XAUUSD_TickBridge.mq5`

Yêu cầu:

- OnTick event.
- SymbolInfoTick.
- CopyTicks reconciliation.
- Batch buffer.
- Persistent local connection.
- Protocol version.
- Reconnection.
- Sequence/checkpoint.
- Health reporting.
- No trade execution.

OnTick không đại diện cho mọi tick riêng biệt.

Giữ event handler ngắn.

Không blocking I/O quá mức trong OnTick.

Kiểm chứng thực tế xem socket transport và buffering nào tương thích MT5 build đang sử dụng.

## 4.2. Shared Data Contract

Mode A và Mode B phải xuất ra cùng canonical tick schema.

Các field bổ sung:

- ingestion_mode.
- source_tick_time.
- gateway_receive_time.
- batch_id.
- source_cursor.
- sequence_id.
- gap_status.

Không cho cùng một tick xuất hiện đồng thời từ A và B trong production stream nếu chưa có cơ chế chọn nguồn rõ ràng.

## 4.3. A/B Benchmark

Chạy hai mode trên cùng terminal, cùng symbol, cùng khoảng thời gian quan sát.

Đo:

- Total source ticks.
- Captured ticks.
- Missing count.
- Duplicates.
- Candle parity.
- CPU/RAM.
- Processing p50/p95/p99.
- Gateway-to-browser latency.
- Recovery behavior.
- Worst observed stalls.

Lưu ý: Nếu benchmark song song có thể gây ảnh hưởng lẫn nhau, phải thực hiện thêm benchmark tuần tự với điều kiện tương đương.

Tách độ trễ đo cùng máy khỏi độ trễ nguồn thị trường không thể quan sát trực tiếp.

## 4.4. Decision Gate

Nếu Mode A đạt mục tiêu về độ đầy đủ, ổn định và latency, cho phép giữ A làm primary.

Nếu Mode B tốt hơn có bằng chứng, cho phép chọn B.

Nếu Mode B không đạt, không để nó trở thành blocker của Strategy Engine.

Lưu phương pháp và kết quả trong:

`MODE_A_B_BENCHMARK.md`

---

# 5. PHASE 3: UNIFIED TRADING RULEBOOK V3 IMPLEMENTATION

Triển khai một Strategy Engine độc lập với data ingestion.

Không đưa logic giao dịch vào WebSocket gateway.

## 5.1. Strategy Modules

Market Regime:
- TRENDING_UP.
- TRENDING_DOWN.
- SIDEWAYS.
- TRANSITION.
- UNKNOWN.

Market Structure:
- HH, HL, LH, LL.
- Swing High/Low.
- BOS/CHoCH.
- Support/Resistance.
- Breakout.
- Failed Breakout.

Indicator Features:
- EMA20/50/100/200.
- RSI14.
- MACD12/26/9.
- ATR14.

Setup:
- Pullback.
- Reversal Candidate.
- Breakout Candidate.
- Relevant Zones.
- Confirmation.
- Entry Window.
- Invalidation.

Decision:
- BUY.
- SELL.
- WAIT.
- BLOCKED.

Lifecycle:
- MISSED.
- EXPIRED.
- INVALIDATED.

## 5.2. Indicator Correctness

Có thể sử dụng pandas-ta-classic sau dependency/license review.

Không bắt buộc tích hợp nếu implementation hiện tại đã chính xác.

Kiểm tra parity với MT5:

- EMA initialization.
- RSI smoothing.
- MACD calculation.
- ATR smoothing.
- Warm-up behavior.
- Closed-bar behavior.
- Missing-bar handling.

Không dùng EMA, RSI và MACD như ba bằng chứng độc lập khi chúng phản ánh các biến đổi từ cùng nguồn giá.

## 5.3. Causal Market Structure

Mỗi cấu trúc phải có:

- formed_at.
- known_at.
- confirmed_at.
- invalidated_at.
- source_timeframe.
- rule_version.

Không sử dụng centered-window swing trước thời điểm xác nhận thực tế.

Tham khảo smart-money-concepts nhưng audit và tái triển khai causal logic nếu cần.

## 5.4. Setup State Machine

Thiết kế:

NO_SETUP
→ SETUP_FORMING
→ PULLBACK_IN_PROGRESS
→ AT_RELEVANT_ZONE
→ AWAITING_CONFIRMATION
→ CONFIRMED
→ AWAITING_ENTRY_WINDOW
→ ENTRY_ELIGIBLE.

Các trạng thái kết thúc:

- INVALIDATED.
- MISSED.
- EXPIRED.
- BLOCKED theo chính sách.

Dùng event-driven transitions.

Mỗi setup có stable setup_id, policy_version và reason codes.

Không phát một setup mới lặp lại trên mọi tick nếu thực chất vẫn là cùng một cơ hội.

## 5.5. BUY/SELL Eligibility

BUY yêu cầu:

- Context phù hợp.
- Relevant support zone.
- Pullback hợp lệ.
- Confirmation theo strategy policy.
- Entry window còn hiệu lực.
- SL/TP hợp lệ.
- Risk preflight đạt.

SELL áp dụng logic tương ứng theo chiều giảm.

Không cần đồng thời RSI, MACD, tất cả EMA và mọi loại confirmation cùng đồng thuận.

WAIT phải ghi lý do cụ thể.

## 5.6. Strategy Research Candidates

Thiết kế:

C0: Minimal baseline được định nghĩa và chốt rõ ràng trong dự án này.

C1: EMA50 + RSI14 + ATR14 + Zone/Price Action.

C2: C1 + Market Structure.

C3: C2 + Pullback Lifecycle.

C4: C3 + Confirmation.

C5: C4 + MACD/extended EMA.

C6: C4/C5 + Entry Timing.

C7: ML Shadow Research.

Không gán nhãn baseline V1.1.0 nếu chưa có baseline đó trong repository.

Không mặc định C7 tốt nhất.

Deliverables:

- UNIFIED_RULEBOOK_V3.md.
- FEATURE_SPEC.md.
- STRATEGY_POLICIES.md.
- SETUP_LIFECYCLE.md.
- DECISION_REASON_CODES.md.

---

# 6. PHASE 4: RISK & ENTRY INTELLIGENCE

Thiết kế module độc lập:

- Planned Entry.
- Entry Window.
- Invalidation.
- Expiration.
- Stop Loss.
- Take Profit.
- R:R.
- ATR-relative stop context.
- Volume estimate.
- Broker constraints.
- Spread allowance.
- Risk budget.

Không hardcode 1 lot = 100 oz.

Đọc symbol metadata thực tế.

Có thể dùng order_calc_profit để ước lượng tổn thất nếu API hỗ trợ mà không gửi lệnh.

Không gọi order_send.

Nếu dữ liệu broker/account thiếu, trả về `RISK_NOT_EVALUABLE` và không đánh dấu ELIGIBLE.

Phân biệt:

- Strategy Eligible.
- Risk Eligible.
- Execution Authorized.

Trong dự án này `Execution Authorized` luôn false.

Tạo test cho:

- Invalid SL.
- Invalid TP.
- Insufficient margin estimate.
- Minimum lot exceeds risk budget.
- Wide spread.
- Entry missed.
- Invalidated setup.
- Account configuration missing.

---

# 7. PHASE 5: DETERMINISTIC REPLAY & BACKTEST

Không được chỉ backtest trên nến rồi tuyên bố kết quả khớp với tick-level live.

## 7.1. Replay

Tạo deterministic replay từ persisted ticks.

Cùng dữ liệu, phiên bản và cấu hình phải tái tạo:

- Candles.
- Features.
- Setup events.
- Decisions.
- Reason codes.

Không sử dụng nến tương lai.

## 7.2. Backtest

Mô phỏng:

- Bid/Ask.
- Spread.
- Entry.
- TP/SL.
- Slippage theo mô hình có công bố.
- Commission.
- Missed orders.
- Timeouts.
- Trading session.
- Account risk.

Nếu cùng một bar OHLC có thể chạm cả SL và TP nhưng không có tick path, đánh dấu kết quả không xác định hoặc áp dụng quy tắc bảo thủ được công bố trước; không tự chọn kịch bản có lợi.

## 7.3. Quantitative Validation

Thực hiện:

- Chronological split.
- Walk-forward testing.
- Purging/embargo khi label overlap.
- Feature ablation.
- Cost sensitivity.
- Regime analysis.
- Out-of-sample reporting.
- False-signal analysis.
- Missed-opportunity analysis.

So sánh các candidate trên cùng tập cơ hội.

Không tối ưu chỉ vì số lệnh quá ít.

Không chỉnh threshold sau khi nhìn holdout để cứu kết quả.

Deliverables:

- REPLAY_VALIDATION.md.
- BACKTEST_REPORT.md.
- STRATEGY_COMPARISON.md.
- DATASET_MANIFEST.md.

Nếu dữ liệu chưa đủ, báo cáo INSUFFICIENT_DATA thay vì kết luận hiệu quả.

---

# 8. PHASE 6: MACHINE LEARNING SHADOW

Chỉ triển khai khi dữ liệu và causal replay đạt yêu cầu.

## Models

A. Market Regime Classification.

B. Pullback Continuation.

C. Confirmation Success.

D. TP Before SL.

E. Expected Net R.

Sử dụng baseline đơn giản trước:

- Logistic Regression.
- Gradient Boosted Trees khi phù hợp.

Không bắt buộc Deep Learning.

## ML Pipeline

- Feature generation.
- Label generation.
- Point-in-time correctness.
- Train/validation/test.
- Model registry.
- Calibration.
- Drift monitoring.
- Shadow prediction logging.

Không sử dụng một model chưa hiệu chuẩn để hiển thị xác suất 80–90% như một sự thật thống kê.

ML không được chặn real-time tick processing.

Có deadline cho inference.

Nếu ML không có kết quả, Rule Engine vẫn hoạt động.

Không sử dụng ML để tự sửa chiến lược hoặc threshold.

---

# 9. PHASE 7: REAL-TIME DASHBOARD UPGRADE

Giữ dashboard hiện tại hoạt động trong quá trình nâng cấp.

Không chuyển sang Next.js chỉ vì kế hoạch ban đầu đề xuất Next.js.

Đánh giá chi phí và rủi ro migration.

Nếu có lợi ích rõ ràng, chuyển dần sang:

- Next.js.
- TypeScript strict.
- Tailwind.
- Lightweight Charts.
- FastAPI/WebSocket backend.

## UI Modules

A. Market Watch.

B. Live M1/M5/M15/H1/H4 Chart.

C. EMA and Market Structure Overlay.

D. RSI/MACD/ATR.

E. Pullback & Price Action.

F. Setup Lifecycle.

G. Decision Intelligence.

H. Entry/SL/TP/Risk.

I. Data Quality & Latency.

J. Replay & Backtest.

K. ML Shadow.

## UI Integrity

Không có tín hiệu giả.

Không tính BUY/SELL riêng ở frontend.

Không dùng historical result làm real-time signal.

Không vẽ lại toàn bộ chart sau mỗi tick.

Không đồng nhất dữ liệu stale với giá mới.

Hiển thị rõ:

- Last tick source time.
- Gateway receive time.
- Render update time.
- Connected/Idle/Stale/Disconnected.
- Data quality state.
- Strategy evaluation time.
- Active policy version.

Đảm bảo biểu đồ M1 có đủ lịch sử backfill để sử dụng, không chỉ 3–4 nến vừa nhận.

---

# 10. PHASE 8: WINDOWS/MAC CROSS-PLATFORM

Windows 11 là data host chính.

MacBook M1 là research/development/dashboard workstation.

Không đòi hỏi Python MetaTrader5 phải chạy native trên macOS ARM.

Hỗ trợ remote dashboard qua LAN hoặc kết nối riêng được bảo vệ.

Không mở gateway công khai ra Internet.

Nếu có môi trường Mac để kiểm thử:

- Browser compatibility.
- Chart performance.
- Remote WebSocket.
- Reconnect.
- Sleep/resume.
- Network changes.
- Authentication.

Nếu không có Mac, đánh dấu NOT_TESTED, không ghi PASS.

---

# 11. OBSERVABILITY & RELIABILITY

Triển khai state machine cho connection:

- CONNECTING.
- CONNECTED_ACTIVE.
- CONNECTED_IDLE.
- STALE.
- RECOVERING.
- DISCONNECTED.
- SOURCE_MISMATCH.
- MARKET_CLOSED khi có đủ bằng chứng.

Không suy luận DISCONNECTED chỉ từ việc 5 giây không có tick.

Phân biệt:

- Transport heartbeat.
- Terminal connection.
- Market session.
- Data freshness.

## End-to-End Latency

Đo riêng:

- MT5 observation to Gateway.
- Gateway processing.
- Gateway to WebSocket.
- WebSocket to Browser.
- Browser rendering.

Chỉ tính chênh lệch timestamp trực tiếp khi đồng hồ có cùng cơ sở thời gian hoặc đã đồng bộ với sai số được định lượng.

Ghi p50/p95/p99 và sample count.

Không báo 7,8 ms gateway latency thành latency end-to-end.

---

# 12. ACCEPTANCE GATES

## Gate A: Data Integrity

- Hai bar lệch được điều tra.
- Cursor regression tests.
- Backfill có manifest.
- Tick storage hoạt động.
- Không silent data loss.
- Closed bar parity có bằng chứng.

## Gate B: Connection Benchmark

- Mode A có kết quả đo.
- Mode B được benchmark hoặc có blocker cụ thể.
- Có lựa chọn primary mode dựa trên bằng chứng.
- Connection recovery được kiểm thử.
- End-to-end latency được đo.

## Gate C: Strategy Correctness

- Rulebook đã triển khai.
- Causal structure tests.
- BUY/SELL/WAIT reason codes.
- Setup lifecycle.
- Không look-ahead.
- Không repaint.

## Gate D: Risk & Replay

- Risk preflight.
- Deterministic replay.
- Cost-aware backtest.
- Strategy comparison.
- Không dùng dữ liệu chưa đạt QA.

## Gate E: ML & Product

- ML Shadow độc lập.
- Dashboard có các module chính.
- Có authentication phù hợp.
- Windows QA.
- Mac QA hoặc NOT_TESTED.
- Recovery documentation.

Các gate có thể được phát triển song song ở phần không phụ thuộc, nhưng không được dùng kết quả chưa chứng nhận để vượt một gate bắt buộc.

---

# 13. ENGINEERING & GIT GOVERNANCE

Trước khi thay đổi:

1. Kiểm tra Git status.
2. Kiểm tra branch và remote.
3. Kiểm tra file người dùng chưa commit.
4. Đọc test hiện tại.
5. Xác định phạm vi thay đổi.

Không force push.

Không xóa tài liệu hoặc dữ liệu người dùng.

Không tự thay đổi remote.

Không commit credentials.

Không tải hoặc chạy repository bên thứ ba chưa kiểm tra license/security.

Mỗi phase phải có:

- Code changes.
- Tests.
- Benchmark nếu phù hợp.
- Acceptance result.
- Known limitations.
- Rollback instructions.

Chỉ commit khi test liên quan đạt và commit scope rõ ràng.

Không tự push lên remote nếu không có quyền được yêu cầu riêng.

---

# 14. REQUIRED IMPLEMENTATION REPORT

Cuối mỗi phase, báo cáo ngắn, có bằng chứng:

1. Mục tiêu.
2. File tạo/sửa.
3. Lệnh test đã chạy.
4. Kết quả PASS/FAIL.
5. Benchmark thực đo.
6. Bug hoặc blocker còn tồn tại.
7. Phần nào chưa triển khai.
8. Gate status.
9. Git status/commit nếu có.
10. Bước tiếp theo.

Dùng trạng thái:

VERIFIED PASS.
PARTIAL.
BLOCKED.
FAILED.
NOT TESTED.

Không dùng "DONE" khi chỉ viết code chưa chạy.

Nếu không truy cập được terminal, không giả mạo kết quả live. Tiếp tục các phần offline có thể kiểm thử.

---

# 15. IMMEDIATE EXECUTION ORDER

Hãy thực hiện ngay trong workspace hiện tại:

P0:
- Audit trạng thái project.
- Reproduce 11 tests.
- Điều tra hai M1 mismatch.
- Bổ sung cursor/duplicate/boundary tests.
- Kiểm tra terminal identity isolation.
- Sửa health-state inconsistencies.

P1:
- Historical M1 backfill.
- Tick persistence.
- Dataset manifest.
- Data quality and rollover quarantine.
- Closed-bar parity validation.

P2:
- MQL5 Mode B read-only bridge.
- Mode A/B benchmark.
- End-to-end latency instrumentation.
- Chọn primary data mode.

P3:
- Causal Market Structure.
- EMA/RSI/MACD/ATR.
- Pullback.
- Confirmation.
- Entry.
- BUY/SELL/WAIT State Machine.

P4:
- Risk Intelligence.
- Setup lifecycle persistence.
- Shadow Decision API.

P5:
- Deterministic replay.
- Backtesting.
- Strategy comparison C0–C7.
- Walk-forward evaluation.

P6:
- ML Shadow.
- Probability calibration.
- Model monitoring.

P7:
- Production-quality local dashboard.
- Network security.
- Windows/Mac compatibility.
- Final QA.

Bạn được quyền thực hiện liên tục các phase trong phạm vi môi trường hiện có, nhưng không được vượt qua bằng tuyên bố PASS giả.

Nếu một phase bị chặn bởi dữ liệu hoặc môi trường bên ngoài, hãy giữ nguyên trạng thái blocker và tiếp tục những module độc lập có thể hoàn thành an toàn.

# FINAL SUCCESS DEFINITION

Dự án đạt mục tiêu khi có:

- MT5 real data connectivity.
- Verified terminal isolation.
- Reliable tick capture.
- Correct M1 candle formation.
- Measured end-to-end latency.
- Persistent historical ticks and bars.
- Data Quality Engine.
- Causal Unified Strategy Engine.
- Explainable BUY/SELL/WAIT decisions.
- Setup Lifecycle.
- Entry & Risk Intelligence.
- Deterministic Replay.
- Cost-aware Backtesting.
- ML Shadow.
- Real-Time Dashboard.
- Windows operation.
- Mac-compatible access path.
- Security and QA evidence.
- Zero live-order execution capability in this release.

Không cần có lợi nhuận dương để tuyên bố phần mềm vận hành đúng.

Nhưng tuyệt đối không được tuyên bố chiến lược có lợi thế giao dịch nếu chưa có bằng chứng ngoài mẫu đáng tin cậy.

**BẮT ĐẦU NGAY: đọc trạng thái repository, điều tra hai nến M1 lệch và triển khai phần dữ liệu còn thiếu trước. Sau khi chứng nhận Data Integrity, tiếp tục Mode B và Unified Strategy Engine theo kế hoạch.**