# MASTER PROMPT V4.2
# XAU/USD TRADING INTELLIGENCE
## Complete the Existing Project, Not Rebuild It
### MetaTrader 5 · Windows 11 · MacBook M1 · Real-Time M1 · Quantitative Strategy · ML Shadow

## 0. ROLE & MISSION

Bạn là Principal Quantitative Trading Architect, MQL5 Engineer, Low-Latency Systems Engineer, Senior Python Engineer, ML Research Scientist, Full-Stack Architect và Independent QA Auditor.

Hãy trực tiếp tiếp tục xây dựng dự án:

**Repository:** https://github.com/howtodonextcom-art/261013-ML-XAUUSD

**Local workspace dự kiến:** `Z:\Coding\261013-ML-XAUUSD`

**Target:** MetaTrader 5, MetaQuotes-Demo, XAUUSD, Windows 11; dashboard và research workstation trên MacBook M1.

Nhiệm vụ cuối cùng:

Xây dựng một Trading Intelligence Terminal hoạt động thực tế, kết nối giá MT5, phân tích nến M1 theo thời gian thực, hiểu cấu trúc thị trường đa khung, nhận diện setup, đưa ra BUY/SELL/WAIT có giải thích, tính Entry/SL/TP/Risk, replay dữ liệu và phát triển Machine Learning Shadow.

**Không chỉ xây dựng một trang biểu đồ có nhiều indicator.**

Hệ thống phải có khả năng trả lời:

1. Thị trường đang diễn biến thế nào?
2. Những cấu trúc và mẫu hình nào đang xuất hiện?
3. Xu hướng có đang tiếp diễn hay suy yếu?
4. Có setup BUY hoặc SELL hợp lệ không?
5. Nếu chưa, chính xác còn thiếu điều kiện gì?
6. Nếu setup bị vô hiệu, nguyên nhân là gì?
7. Nếu Entry đã trôi qua, có cần bỏ qua cơ hội không?
8. Rủi ro giao dịch giả định là bao nhiêu?
9. Kết quả các chiến lược có thực sự tốt hơn baseline không?
10. Dữ liệu và dự báo có đủ đáng tin để hỗ trợ quyết định không?

Tất cả phải dựa trên thông tin thực sự được biết tại thời điểm đánh giá.

---

# 1. EXISTING PROJECT BASELINE

Repository đã được push lên GitHub.

Commits được báo cáo:

- f156814: Phase 1A/1B, data integrity.
- 14b947c: CLAUDE.md và project governance.

Trước khi làm việc:

- Kiểm tra Git HEAD, branch, remote và working tree.
- Đọc CLAUDE.md.
- Đọc README.md.
- Đọc toàn bộ docs/architecture và docs/qa.
- Đọc mã nguồn trong services/gateway.
- Đọc toàn bộ tests và benchmarks.
- Kiểm tra configs/source.json tại local, tuyệt đối không công khai.
- Kiểm tra data/store và manifest SQLite.
- Kiểm tra dữ liệu QA chưa commit.
- Chạy lại test suite.
- Kiểm tra terminal MT5 chính xác.

Kết quả đã báo cáo:

- 35/35 tests PASS, trong đó có 4 live integration tests.
- MetaQuotes-Demo identity isolation.
- Mode A MT5 Python connector.
- M1/M5/M15/H1/H4 candle aggregation.
- WebSocket dashboard.
- Parquet + SQLite storage.
- Idempotent historical backfill.
- Data Quality report.
- 2399/2399 eligible M1 bars exact.
- Một M1 bar bị quarantine.
- Một capture live 417 giây khớp 1806/1806 tick.
- Gateway p50 khoảng 3,5 ms, không phải end-to-end latency.

Đây là baseline theo báo cáo, phải kiểm tra lại bằng môi trường và dữ liệu hiện có.

**KHÔNG được làm lại những module đang hoạt động chỉ vì muốn thay framework.**

Chỉ refactor khi có bằng chứng lỗi, thiếu năng lực hoặc benchmark chứng minh lợi ích.

---

# 2. ABSOLUTE SAFETY CONSTRAINTS

Ứng dụng duy trì:

`READ_ONLY + SHADOW + PAPER_SIMULATION`

Không triển khai khả năng gửi lệnh thật trong release này.

Cấm trực tiếp hoặc gián tiếp:

- mt5.order_send().
- MQL5 OrderSend().
- OrderSendAsync().
- CTrade execution methods.
- API sửa hoặc đóng vị thế thật.
- Hidden auto-trading.
- Trading execution qua subprocess hoặc third-party wrapper.

Hệ thống chỉ phân tích, đề xuất và mô phỏng.

Giá trị BUY/SELL trong ứng dụng là **research decision**, không phải lệnh broker đã thực hiện.

Kiến trúc phải bảo đảm việc thay đổi frontend hoặc cấu hình không tự mở quyền giao dịch.

Không cho ML tự sửa strategy policy hoặc gửi lệnh.

Không tự chuyển sang FTMO nếu MetaQuotes-Demo gặp lỗi.

Không hứa độ trễ bằng 0 ms hoặc khả năng dự báo chắc chắn nến tiếp theo.

---

# 3. PHASE P1C: COMPLETE & HARDEN DATA INTEGRITY

Đây là công việc đầu tiên.

## 3.1. Critical Code Audit

Điều tra những rủi ro đã được nhận diện trong source hiện tại:

A. LiveTickWriter chunk identity có thể trùng sau restart khi bridge_seq được reset.

B. Cursor checkpoint và persisted ticks có thể thiếu atomic consistency.

C. read_table("ticks") có thể trộn historical/live ticks.

D. Data Quality parity chưa filter chặt theo dataset/source/server/symbol.

E. covered_minutes() giả định hourly tick chunk đầy đủ mọi phút.

F. Backfill identity verification chưa thống nhất với live source.

G. seed_from_store() chưa cô lập đúng symbol và quarantine state.

H. live_vs_history.py có hardcoded terminal và chưa cô lập capture session.

I. Server-time/UTC assumption chưa được đối chiếu đầy đủ với tài liệu MT5 và môi trường thực.

J. quality.py có giả định tick size cố định 0.01.

K. README và một số tài liệu vẫn mô tả trạng thái Phase 0 cũ.

Không được mặc định các rủi ro trên đều là lỗi đã xảy ra. Viết test tái hiện rồi mới sửa.

## 3.2. Storage Identity

Thêm capture_session_id hoặc định danh phiên tương đương để không nhầm dữ liệu giữa các lần restart.

Canonical dataset phải được phân biệt bằng:

- Source ID.
- Terminal identity.
- Broker server.
- Symbol.
- Capture session.
- Dataset version.
- Provenance.
- Quality state.

Lưu raw ticks bất biến.

Không để historical backfill vô tình supersede một phiên live khác.

## 3.3. Crash & Recovery

Kiểm thử:

- Process crash trước khi writer flush.
- Crash sau khi ghi Parquet nhưng trước checkpoint.
- Crash sau checkpoint nhưng trước hoàn tất ghi dữ liệu.
- Restart với cùng cursor.
- Restart sau nhiều phút mất kết nối.
- Recover từ persisted tick watermark.
- Overlap recovery.
- Duplicate-looking ticks.
- Multiple ticks in same millisecond.

Bảo đảm không có silent data loss.

Nếu exactly-once tuyệt đối không thể chứng minh do MT5 không cung cấp unique tick ID, công bố rõ mức đảm bảo thực tế.

## 3.4. Historical/Live Seam

Báo cáo trước cho thấy gap 2563 giây giữa historical data và live capture.

Triển khai:

- Gap inventory.
- Source-compatible backfill.
- Seam reconciliation.
- Duplicate-safe merging.
- Quality flags.
- Coverage report.

Không đánh dấu dữ liệu liên tục nếu vẫn còn khoảng trống.

Nếu MT5 không cung cấp dữ liệu cho một khoảng thời gian, giữ gap là unresolved.

## 3.5. Historical Multi-Timeframe

Backfill hoặc tổng hợp đúng từ M1:

- M5.
- M15.
- H1.
- H4.

Cần kiểm tra dữ liệu đủ dài cho indicator warm-up, đặc biệt EMA200 trên H4.

Không dùng một tuần dữ liệu M1 để giả định EMA200 H4 đã đủ.

Khung H4 phải sử dụng chính xác quy ước time bucket của broker, kể cả session boundary và DST nếu có.

Không tạo synthetic candle trong khoảng không có giao dịch.

## 3.6. Documentation Completion

Bắt buộc tạo/cập nhật:

- HISTORICAL_DATA_SPEC.md.
- BACKFILL_REPORT.md.
- DATA_QUALITY_REPORT.md.
- STORAGE_RECOVERY.md.
- SOURCE_IDENTITY.md.
- DATASET_MANIFEST.md.
- README.md.
- KNOWN_LIMITATIONS.md.

Phải đưa số liệu thực tế và test evidence.

## Gate A+

Chỉ PASS khi:

- Không có lỗi dữ liệu nghiêm trọng chưa được quản lý.
- Không có silent duplication/loss.
- Checkpoint recovery đã kiểm thử.
- Historical/live seam được đối chiếu.
- Source/server isolation đạt test.
- M1 parity được báo cáo cả tỷ lệ eligible và coverage tổng thể.
- Bar quarantined không âm thầm đi vào tập huấn luyện được chứng nhận.
- Tài liệu đồng bộ với code.

Chạy thêm capture qua nhiều giai đoạn thị trường khi có điều kiện.

Không chặn những module độc lập chỉ vì thời gian live capture chưa đủ dài.

---

# 4. PHASE P2: LOW-LATENCY DATA ENGINE & MODE B

## 4.1. Mode A

Giữ MT5 Python Connector hiện tại làm control.

Không thay polling interval tùy tiện.

Đo:

- Tick acquisition lag.
- Batch size.
- CPU/RAM.
- Data completeness.
- Queue depth.
- Reconnect behavior.
- Burst processing.

Không coi receipt-to-publish latency là tổng latency.

## 4.2. Mode B MQL5 EA

Xây dựng EA chỉ đọc:

`XAUUSD_TickBridge.mq5`

Chức năng:

- OnTick().
- SymbolInfoTick().
- CopyTicks() reconciliation.
- Local streaming connection.
- Buffering.
- Heartbeat.
- Reconnect.
- Sequence.
- Data gap detection.
- Status reporting.

OnTick không bảo đảm có callback riêng cho mỗi tick, nên phải có reconciliation.

Không thực hiện xử lý nặng hoặc blocking I/O trong OnTick.

Không có bất kỳ trading function nào trong EA.

## 4.3. Mode A/B Benchmark

Cả hai mode phải dùng cùng dữ liệu MetaQuotes-Demo XAUUSD.

So sánh:

- Tick coverage.
- Missing/extra observed ticks.
- Candle parity.
- Gateway p50/p95/p99.
- Browser delivery.
- End-to-end latency.
- CPU/RAM.
- Recovery time.
- Long-running stability.

Tránh để hai nguồn cùng ghi trùng một active dataset.

Dữ liệu benchmark phải có capture_session_id và provenance.

Nếu Mode B không có lợi thế thực tế, được quyền giữ Mode A.

Không biến Mode B thành điều kiện bắt buộc cho Strategy Engine.

## 4.4. End-to-End Latency

Đo các mốc:

MT5 observed tick
→ Gateway received
→ Candle updated
→ Features updated
→ Decision evaluated
→ WebSocket sent
→ Browser received
→ Chart painted.

Đối với các đồng hồ khác nhau, phải có clock-offset estimation hoặc phương pháp đo được chứng minh tương đương.

Chỉ báo cáo latency ở những đoạn có thể đo đáng tin cậy.

Có percentile, sample size và sai số đo.

Không báo toàn hệ thống dưới 10 ms chỉ dựa vào gateway latency.

## Gate B

- Mode B có compile/runtime evidence hoặc blocker cụ thể.
- Mode A/B comparison có kết quả đáng tin.
- Primary mode được chọn bằng benchmark.
- Recovery và WebSocket health tests đạt.
- Có end-to-end latency report.

---

# 5. PHASE P3: MULTI-TIMEFRAME MARKET INTELLIGENCE

Triển khai backend phân tích thị trường độc lập với gateway.

Đầu vào là immutable point-in-time market snapshot.

## 5.1. Market Context

Phân tích:

H4 → xu hướng lớn.

H1 → xu hướng giao dịch.

M15 → vùng giá và setup.

M5 → xác nhận cấu trúc.

M1 → Price Action và Entry timing.

Đây là phân công nghiên cứu mặc định, không phải một chiến lược duy nhất bắt buộc.

So sánh thêm các biến thể có xác nhận ít hơn.

## 5.2. Indicator Engine

Triển khai:

EMA20/50/100/200.

RSI14.

MACD12/26/9.

ATR14.

Các feature:

- EMA slope.
- EMA alignment.
- EMA distance/ATR.
- EMA compression.
- RSI regime.
- RSI momentum.
- MACD histogram slope.
- MACD cross age.
- ATR percentile.
- ATR ratio.
- Spread/ATR.

Có thể dùng pandas-ta-classic hoặc thư viện tương đương sau license/compatibility review.

Bắt buộc kiểm tra parity trên MT5.

Không tính indicator từ candle chưa đóng khi policy yêu cầu closed-bar confirmation.

Nếu chưa đủ dữ liệu warm-up, trả về `INSUFFICIENT_HISTORY`.

## 5.3. Causal Market Structure

Phát hiện:

- HH/HL/LH/LL.
- Swing High/Low.
- BOS.
- CHoCH.
- Support/Resistance.
- Breakout.
- False Breakout.
- Liquidity Sweep Candidate.

Mỗi feature:

event_time,
formed_at,
known_at,
evaluated_at,
source_timeframe,
feature_version.

Không sử dụng future pivots trước thời điểm được xác nhận.

Không repaint tín hiệu đã phát trong quá khứ.

## 5.4. Market Regime

Phân loại:

- TRENDING_UP.
- TRENDING_DOWN.
- SIDEWAYS.
- COMPRESSION.
- VOLATILITY_EXPANSION.
- TRANSITION.
- UNKNOWN.

Không suy diễn ATR cao nghĩa là giá tăng.

Không coi RSI >70 là SELL.

Không coi MACD crossover là lệnh giao dịch.

## Gate C1

- Indicator parity tests đạt.
- Có đầy đủ causal timestamps.
- Multi-timeframe snapshots nhất quán.
- No-lookahead tests đạt.
- Không tạo hướng thị trường giả từ dữ liệu thiếu.

---

# 6. PHASE P4: SETUP LIFECYCLE & DECISION BRAIN

Áp dụng Unified Rulebook V3 từ 12 bài học:

57 Pullback,
62 EMA,
63 RSI,
64 RSI70,
65 MACD,
66 ATR,
69 Minimal Indicator System,
70 Trading Strategy,
71 Entry,
72 Confirmation,
73 No Setup,
74 Full Setup.

## 6.1. Primary Candidate

Chiến lược nghiên cứu:

Multi-Timeframe Trend Pullback
+ Relevant Zone
+ Price Action Confirmation
+ Risk-Controlled Entry.

Không xem đây là chiến lược có lợi nhuận đã được chứng minh.

## 6.2. Pullback & Price Action

Phát hiện:

- Pullback initiation.
- Retracement depth.
- Support/Resistance touch.
- Rejection.
- Pin Bar.
- Engulfing.
- Strong Close.
- Breakout-Retest.
- Pullback continuation.
- Reversal risk.
- Failed setup.

Phải có định nghĩa định lượng và test.

Ví dụ Pin Bar phải xét tỷ lệ bóng/thân, vị trí đóng cửa, biên độ ATR, vị trí vùng giá và khung thời gian.

Không dùng tên mẫu hình chỉ dựa trên trực giác.

## 6.3. Setup State Machine

Duy trì:

NO_SETUP
→ SETUP_FORMING
→ PULLBACK_IN_PROGRESS
→ AT_RELEVANT_ZONE
→ AWAITING_CONFIRMATION
→ CONFIRMED
→ ENTRY_WINDOW
→ ENTRY_ELIGIBLE.

Terminal states:

- INVALIDATED.
- MISSED.
- EXPIRED.

Execution Gate:

- BLOCKED.

Mỗi setup có ID ổn định.

Không tạo hàng trăm setup trùng nhau từ các tick liên tiếp.

Phải theo dõi invalidation và expiration.

## 6.4. BUY/SELL/WAIT

BUY/SELL chỉ xuất hiện khi Rulebook cho phép một setup đạt điều kiện chiến lược.

Risk và execution permission được kiểm tra riêng.

WAIT phải trả về nguyên nhân cụ thể:

- NO_DIRECTION.
- NO_RELEVANT_ZONE.
- AWAITING_PULLBACK.
- PULLBACK_IN_PROGRESS.
- AWAITING_CONFIRMATION.
- SIGNAL_CONFLICT.
- ENTRY_WINDOW_NOT_OPEN.
- INSUFFICIENT_HISTORY.
- DATA_STALE.

Nếu setup đủ điều kiện nhưng spread quá rộng, phải hiển thị Strategy Eligible + Gate Blocked.

Nếu thiếu xu hướng đồng thời spread rộng, không được hiển thị spread là nguyên nhân duy nhất.

## 6.5. Explainability

Mỗi quyết định có:

- Strategy version.
- Dataset version.
- Snapshot time.
- Setup ID.
- Direction.
- Market context.
- Evidence list.
- Missing evidence.
- Invalidation level.
- Next required event.
- Primary reason.
- All reasons.

Không để frontend tự tính BUY/SELL.

## Gate C2

- State transitions được test.
- Có BUY/SELL/WAIT theo policy giả định.
- Không có BUY/SELL vô điều kiện từ một indicator.
- Replay tạo cùng reason code.
- Có trace đầy đủ cho từng setup.

---

# 7. PHASE P5: ENTRY, RISK & SHADOW OUTCOME

Triển khai Risk Engine độc lập.

## Entry

- Planned Entry.
- Entry Window.
- Maximum Chase Distance.
- Confirmation Age.
- Entry Expiration.
- Missed Opportunity.

## Risk

- Structural SL.
- ATR/Execution Buffer khi policy sử dụng.
- Take Profit.
- Gross R:R.
- Expected Net R khi có mô hình được kiểm định.
- Spread.
- Commission.
- Slippage allowance.
- Contract size.
- Volume min/max/step.
- Margin estimate.
- Account risk budget.

Không mặc định 1 lot = 100 oz cho mọi broker.

Dùng thông số thực tế của symbol.

Có thể dùng MT5 order_calc_profit để nghiên cứu P/L mà không gửi lệnh.

Nếu dữ liệu không đủ, phải trả `RISK_NOT_EVALUABLE`.

Không giả định tài khoản MetaQuotes-Demo là tài khoản FTMO.

## Shadow Outcome

Mô phỏng:

- Hypothetical Entry.
- Fill/No Fill.
- TP First.
- SL First.
- Timeout.
- Inconclusive.
- Net P/L estimate.

Không ghi nhận một setup đúng hướng là giao dịch đã thắng nếu không thể khớp Entry.

Không áp dụng hindsight để chọn giá đẹp.

## Gate D1

- Risk calculations được test.
- Broker constraints được tôn trọng.
- Shadow results tách biệt hoàn toàn khỏi live account.
- Không tồn tại đường gửi lệnh thật.

---

# 8. PHASE P6: REPLAY & RESEARCH BACKTEST

## Deterministic Replay

Cùng dữ liệu, policy, seed và code version phải tạo ra cùng:

- Candles.
- Indicators.
- Structure.
- Setup events.
- Decision events.
- Risk result.

Replay phải mô phỏng thông tin được biết theo thời gian.

Không dùng historical swing confirmation sớm hơn thực tế.

## Strategy Candidates

C0: Minimal pre-registered baseline.

C1: EMA50 + RSI14 + ATR14 + Price Action.

C2: C1 + Structure.

C3: C2 + Pullback Lifecycle.

C4: C3 + Confirmation.

C5: C4 + MACD/Extended EMA.

C6: C4/C5 + Entry Window Optimization.

C7: ML Shadow.

C0 phải được định nghĩa trong dự án hiện tại, không tự gọi là V1.1.0 nếu repository không chứa baseline đó.

## Metrics

Đánh giá:

- Total opportunities.
- Eligible setups.
- Executed paper fills.
- Missed setups.
- Invalidations.
- Win rate.
- Average Win.
- Average Loss.
- Expected Net R.
- Profit Factor.
- Maximum Drawdown.
- Trade frequency.
- Calibration khi có xác suất.
- Results by market regime.

So sánh trên cùng tập dữ liệu và tập cơ hội ban đầu.

## Statistical Validation

- Chronological split.
- Walk-forward.
- Purge/embargo nếu nhãn chồng lấn.
- Out-of-sample.
- Cost sensitivity.
- Ablation.
- Overfitting controls.

Không lựa chọn chiến lược thắng chỉ từ in-sample results.

Nếu dữ liệu không đủ để kết luận, báo cáo INSUFFICIENT_EVIDENCE.

## Gate D2

- Replay deterministic.
- No leakage.
- Cost-aware results.
- Candidate comparison.
- Giới hạn thống kê được công bố.

---

# 9. PHASE P7: MACHINE LEARNING SHADOW

ML là nghiên cứu độc lập, không quyết định thực thi.

Các mô hình mục tiêu:

A. Market Regime.

B. Pullback Continuation.

C. Confirmation Outcome.

D. TP Before SL.

E. Expected Net R.

Ưu tiên Logistic Regression và Gradient Boosting làm mô hình đối chứng.

Chỉ xem xét Deep Learning khi có dữ liệu và bằng chứng cải thiện.

Bắt buộc:

- Point-in-time features.
- Label definitions.
- Leakage checks.
- Out-of-sample evaluation.
- Brier Score.
- Log Loss.
- Calibration curve.
- Model versioning.
- Drift monitoring.
- Shadow inference timeout.

Không tự gán confidence 70%, 80% hoặc 90% nếu chưa hiệu chuẩn.

Không dùng dữ liệu quarantine làm training mặc định.

Không cho model sửa baseline.

Nếu ML chưa tốt hơn Rule Engine, giữ ML ở chế độ nghiên cứu hoặc vô hiệu hóa.

## Gate E1

- Có dataset đáng tin.
- Model card.
- Evaluation.
- Calibration.
- So sánh với baseline.
- Không ảnh hưởng đến hoạt động real-time.

---

# 10. PHASE P8: PROFESSIONAL REAL-TIME DASHBOARD

Nâng cấp từ dashboard hiện tại thành Trading Intelligence Terminal dùng được hàng ngày.

Không viết lại toàn bộ giao diện chỉ vì Master Prompt cũ đề xuất Next.js.

Có thể dùng Next.js + TypeScript strict + Tailwind nếu migration thực sự hợp lý.

## Required Panels

### A. Live Market

- Bid/Ask.
- Spread.
- M1 forming candle.
- M5/M15/H1/H4.
- Source and server.
- Connection state.
- Data freshness.

### B. Market Structure

- Trend.
- HH/HL/LH/LL.
- BOS/CHoCH.
- Zones.
- Key levels.

### C. Indicator Intelligence

- EMA overlays.
- RSI.
- MACD.
- ATR.
- Volatility regime.

### D. Setup Intelligence

- Active setup.
- Direction.
- Formation stage.
- Confirmation.
- Invalidation.
- Next required event.

### E. Decision Intelligence

- BUY/SELL/WAIT/BLOCKED.
- Reason codes.
- Readiness.
- Strategy version.

### F. Entry & Risk

- Proposed Entry.
- SL.
- TP.
- R:R.
- Estimated Lot.
- Risk status.
- Expiration.

### G. Replay & Research

- Setup history.
- Strategy comparison.
- Backtest reports.
- ML Shadow outcome.

### H. Data & Performance

- Tick rate.
- Coverage.
- Staleness.
- Gaps.
- Latency p50/p95/p99.
- Queue utilization.
- Reconnection.
- Latest health check.

## UX Requirements

- Desktop 1440×900 primary.
- Laptop 1152×720 secondary.
- Responsive narrow screens.
- Clear typographic hierarchy.
- Chart-first layout.
- Dark mode.
- No fake live state.
- No unnecessary chart redraw.
- No front-end strategy duplication.

Biểu đồ phải có lịch sử đủ dài, không chỉ vài nến từ thời điểm gateway khởi động.

UI chỉ là lớp hiển thị kết quả backend.

## Cross-platform

Windows 11:

MT5 + Data Gateway + Intelligence + Dashboard.

MacBook M1:

Browser client + research/development components.

Ưu tiên kết nối Mac tới Windows qua VPN/SSH tunnel hoặc phương án private network an toàn.

Không expose gateway MT5 trực tiếp ra Internet.

Nếu không thể kiểm thử Mac, báo NOT_TESTED.

## Gate E2

- Dashboard phản ánh backend chính xác.
- Real-time chart hoạt động.
- Multi-timeframe chart hoạt động.
- Explainable decisions.
- No UI/backend disagreement.
- Authentication/network controls.
- Windows QA.
- Mac QA hoặc NOT_TESTED.

---

# 11. QA, SECURITY & RELEASE GOVERNANCE

## Test Categories

- Unit.
- Integration.
- Property-based khi phù hợp.
- Synthetic replay.
- Historical replay.
- Performance.
- Failure injection.
- Security.
- End-to-end browser.

Giữ tests không cần MT5 tách biệt tests cần terminal thật.

CI không được mặc định có terminal MetaQuotes-Demo.

Không báo PASS cho integration test bị skip.

## Data Integrity Regression

Bắt buộc kiểm tra lại lỗi cursor duplication từng tạo ra 104826 tick từ nguồn chỉ có 3925 tick history.

Không để lỗi này tái xuất hiện sau refactor.

## Public GitHub Security

Repository hiện được public.

Không commit:

- MT5 credentials.
- Account ID.
- configs/source.json.
- data/store.
- Secrets.
- Personal computer paths không cần thiết.
- Private screenshots trong image/.
- Local logs chứa định danh.
- Private datasets.

Không viết lại lịch sử hai commit đã push.

Giữ quy tắc Git identity trong CLAUDE.md.

Không force push.

Chỉ push khi phù hợp với quyền và chỉ dẫn đã được người dùng cho phép.

## Release Documentation

Cần có:

- README.md.
- INSTALL_WINDOWS.md.
- ACCESS_MACBOOK_M1.md.
- DATA_INTEGRITY_REPORT.md.
- LOW_LATENCY_BENCHMARK.md.
- UNIFIED_RULEBOOK_V3.md.
- FEATURE_SPEC.md.
- SETUP_LIFECYCLE.md.
- RISK_GOVERNANCE.md.
- REPLAY_REPORT.md.
- BACKTEST_REPORT.md.
- ML_MODEL_CARD.md.
- QA_ACCEPTANCE.md.
- ROLLBACK_PLAN.md.
- KNOWN_LIMITATIONS.md.

Các báo cáo chỉ được chứa số liệu đã thực hiện.

---

# 12. EXECUTION STRATEGY

Hãy trực tiếp làm việc trong repository hiện tại.

Không hỏi người dùng những câu đã có câu trả lời từ workspace.

Không dừng sau audit để hỏi nên đi tiếp Phase nào.

Bạn được phép tự quyết định thứ tự công việc con miễn không vi phạm acceptance dependencies.

Thực hiện:

AUDIT → FIX → IMPLEMENT → TEST → BENCHMARK → DOCUMENT.

Ưu tiên hoàn thành P1C trước.

Trong lúc Mode B đang bị chặn bởi công cụ biên dịch hoặc MT5, có thể triển khai Strategy Engine bằng dữ liệu replay được chứng nhận.

Không tự tuyên bố một phase hoàn thành chỉ vì source code đã tồn tại.

Nếu cần sự tương tác thủ công như cấp quyền socket cho MQL5, chỉ rõ thao tác cần thực hiện và tiếp tục những việc độc lập.

Không hứa thực hiện công việc khi môi trường chưa sẵn sàng.

## Phase Report Format

Mỗi phase phải báo cáo:

- Files changed.
- Features implemented.
- Tests PASS/FAIL/SKIP.
- Measured performance.
- Known limitations.
- Data provenance.
- Gate status.
- Git status.
- Next actionable work.

Sử dụng:

VERIFIED PASS,
PARTIAL,
BLOCKED,
FAILED,
NOT TESTED.

Không dùng "DONE" thay cho bằng chứng.

---

# 13. PRIORITY ORDER

P0: Security & Data Integrity.

P1: Crash-safe Persistence + Dataset Isolation.

P2: Mode B + A/B Benchmark + E2E Latency.

P3: Multi-Timeframe + Indicators + Causal Structure.

P4: Pullback + Confirmation + Setup Lifecycle.

P5: BUY/SELL/WAIT + Entry/Risk.

P6: Deterministic Replay + Backtesting.

P7: ML Shadow.

P8: Professional Dashboard + Mac Compatibility + Security QA.

Không để P2 làm trì hoãn vô hạn P3 nếu Mode A đã có đủ dữ liệu được kiểm chứng.

---

# 14. FINAL ACCEPTANCE STANDARD

Không đánh giá thành công dự án bằng số dòng code, số indicator hay số tín hiệu BUY/SELL.

Dự án phải chứng minh:

1. Nhận dữ liệu MT5 đúng nguồn.
2. Không mất dữ liệu âm thầm.
3. Candle M1 chính xác và có provenance.
4. Có latency measurement đáng tin.
5. Có Multi-Timeframe Intelligence.
6. Có cấu trúc thị trường causal.
7. Có Rulebook V3 chạy thật.
8. Có Setup Lifecycle.
9. Có BUY/SELL/WAIT được giải thích.
10. Có Risk và Entry Planning.
11. Có deterministic replay.
12. Có backtest sau chi phí.
13. Có ML Shadow được kiểm chứng hoặc bị từ chối bằng bằng chứng.
14. Có dashboard hoạt động và phản ánh backend.
15. Không có khả năng gửi lệnh thật.
16. Có rollback, recovery và QA evidence.
17. Có hướng dẫn Windows và MacBook M1.
18. Không tuyên bố độ chính xác dự báo hoặc lợi nhuận chưa được chứng minh.

## BEGIN EXECUTION NOW

Bắt đầu bằng việc đọc repository hiện tại, kiểm tra các rủi ro đã được phát hiện trong storage/quality/cursor/backfill, hoàn thiện Gate A+, rồi trực tiếp xây dựng phần còn lại.

**Mục tiêu cuối cùng là một XAU/USD Trading Intelligence Terminal đáng tin cậy, nhanh, giải thích được và có thể kiểm chứng, không phải một indicator dashboard đơn thuần.**

