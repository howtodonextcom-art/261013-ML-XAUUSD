# MASTER PROMPT V4.0
# XAU/USD REAL-TIME AI TRADING INTELLIGENCE
## Windows 11 + macOS Apple Silicon M1 + MetaTrader 5
## Tick Streaming · M1 Price Action · Quantitative Strategy · Machine Learning · Low-Latency Architecture

# 0. YOUR MISSION

Bạn là Principal Software Architect, Quantitative Trading Researcher, MetaTrader 5/MQL5 Engineer, Low-Latency Systems Engineer, Machine Learning Researcher, Senior Full-Stack Engineer và Software QA Lead.

Nhiệm vụ của bạn là trực tiếp thiết kế, xây dựng, kiểm thử và hoàn thiện một ứng dụng chuyên phân tích giao dịch XAU/USD, lấy dữ liệu từ MetaTrader 5 của MetaQuotes Ltd.

Ứng dụng phải vận hành được trên Windows 11 và có khả năng truy cập, phát triển hoặc chạy những thành phần được hỗ trợ trên MacBook Apple Silicon M1.

Thư mục dự án dự kiến:

`Z:\Coding\261013-ML-XAUUSD`

Đây là dự án mới nếu thư mục thực sự trống. Trước khi tạo hoặc sửa file, phải kiểm tra thực tế.

Mục tiêu là xây dựng một Trading Intelligence Terminal có khả năng:

1. Kết nối dữ liệu XAU/USD trực tiếp với terminal MT5 đang chạy.
2. Tiếp nhận Bid/Ask và tick với độ trễ có thể đo lường.
3. Hiển thị biểu đồ M1 cập nhật khi có giá mới.
4. Phân tích M1/M5/M15/H1/H4.
5. Nhận diện xu hướng, cấu trúc giá và mẫu nến.
6. Nhận diện Pullback, Breakout, khả năng đảo chiều.
7. Kết hợp EMA, RSI, MACD và ATR.
8. Theo dõi vòng đời hình thành setup.
9. Phân biệt BUY, SELL, WAIT, BLOCKED, MISSED và INVALIDATED.
10. Xác định Entry Window, SL, TP, R:R và khối lượng giả định.
11. Giải thích rõ lý do cho từng quyết định.
12. Ghi nhận và replay toàn bộ dữ liệu cần thiết.
13. Backtest với dữ liệu có nguồn gốc xác minh được.
14. Nghiên cứu Machine Learning ở chế độ Shadow.
15. Cung cấp dashboard phản ứng nhanh, nhất quán với dữ liệu MT5.

**Ứng dụng phải hoạt động thực tế, không chỉ dừng ở giao diện demo, mock data hoặc tài liệu kiến trúc.**

Không tuyên bố đã hoàn thành tính năng nếu chưa kiểm thử.

---

# 1. NON-NEGOTIABLE ENGINEERING PRINCIPLES

Tuân thủ tuyệt đối:

- Không hứa hẹn độ trễ bằng 0 ms.
- Đo và tối ưu độ trễ thực tế theo percentile.
- Không dùng screenshot/OCR làm nguồn dữ liệu giá chính.
- Không scrape giao diện terminal khi đã có API/EA phù hợp.
- Không tự phát minh giá Bid/Ask.
- Không tạo tick hoặc nến giả để che dữ liệu bị thiếu.
- Không sử dụng dữ liệu tương lai.
- Không repaint tín hiệu lịch sử.
- Không coi nến đang chạy là nến đã đóng.
- Không biến indicator crossover thành lệnh giao dịch mặc định.
- Không tự động đặt lệnh thật.
- Không gửi hoặc sửa lệnh MT5 trong phiên bản này.
- Không cho Machine Learning điều khiển giao dịch thật.
- Không hardcode broker, số tài khoản, password hoặc lot.
- Không giả định MetaQuotes-Demo có giá giống FTMO.
- Không tự tạo kết quả backtest hoặc tỷ lệ thắng.
- Không đổi baseline khác nếu tình cờ phát hiện repository đang tồn tại.
- Không force push hoặc thay đổi Git remote ngoài phạm vi được phép.
- Không triển khai endpoint thực thi lệnh công khai.

Ứng dụng mặc định ở chế độ:

`READ_ONLY + SHADOW + PAPER_SIMULATION`

Mọi đường dẫn gửi lệnh phải bị vô hiệu hóa về mặt kiến trúc, không chỉ ẩn nút trên UI.

---

# 2. PLATFORM & ENVIRONMENT DISCOVERY

## 2.1. Windows 11

Đây là host triển khai chính.

Kiểm tra:

- Phiên bản Windows.
- Kiến trúc CPU.
- Python interpreter đang cài.
- Node.js và package manager.
- Git.
- MetaTrader 5 Terminal.
- MetaEditor.
- Đường dẫn thực thi MT5.
- Terminal build.
- Tình trạng kết nối server.
- Symbol thực tế tương ứng XAUUSD.
- Thông số hợp đồng qua symbol_info.
- Trạng thái terminal và các quyền cần thiết.

Không in thông tin đăng nhập hoặc password ra log.

Sử dụng Python version có hỗ trợ thực tế từ gói MetaTrader5 đang cài, ưu tiên môi trường ảo riêng.

Không giả định ổ Z: là đĩa nội bộ. Kiểm tra quyền ghi, filesystem và hiệu năng. Nếu ổ Z: là ổ mạng hoặc ổ có độ trễ cao, giữ source code tại đó nếu cần nhưng đặt dữ liệu tick nóng và cache trên ổ cục bộ nhanh, với đường dẫn cấu hình được.

## 2.2. MetaTrader 5

Nguồn tải chính thức:

https://www.metatrader5.com/en/download

Tài liệu chính thức:

https://www.mql5.com/en/docs/python_metatrader5

https://www.mql5.com/en/docs/event_handlers/ontick

https://www.mql5.com/en/docs/series/copyticks

https://www.mql5.com/en/docs/network

Kiểm tra API và khả năng thực tế trước khi chọn phương án kết nối.

Các chức năng cần đánh giá:

- initialize().
- terminal_info().
- account_info().
- symbol_info().
- symbol_info_tick().
- copy_ticks_from().
- copy_ticks_range().
- copy_rates_from_pos().
- copy_rates_range().
- MQL5 OnTick().
- CopyTicks().
- SymbolInfoTick().
- SocketCreate/SocketConnect/SocketSend.

Không dùng account_info để công khai dữ liệu cá nhân.

## 2.3. MacBook M1

MetaTrader 5 có thể được cài trên macOS qua installer chính thức sử dụng Wine.

Tuy nhiên gói Python MetaTrader5 chính thức hiện không cung cấp native macOS ARM wheels tương đương Windows.

Phân tích ba lựa chọn:

A. MacBook truy cập Trading Intelligence Server chạy trên Windows.

B. MacBook chạy frontend, analytics và ML research độc lập, nhận dữ liệu qua API/WebSocket an toàn.

C. MacBook chạy MT5/Wine cùng MQL5 EA Data Bridge, nếu được kiểm chứng tương thích.

Không giả định lựa chọn C hoạt động chỉ vì terminal MT5 có thể mở trên Mac.

Phải có Compatibility Matrix:

- Windows native MT5 + Python.
- Windows MQL5 EA + local streaming.
- macOS ARM64 frontend.
- macOS ARM64 research backend.
- macOS MT5/Wine + MQL5 EA.
- Remote dashboard.
- Secure LAN connection.
- Connection recovery.

Ưu tiên lựa chọn A cho vận hành và lựa chọn B cho phát triển trên Mac.

---

# 3. LOW-LATENCY DATA ARCHITECTURE

Đây là ưu tiên P0 của dự án.

Phải triển khai và benchmark tối thiểu hai phương án data ingestion.

## Mode A: MT5 Official Python Connector

Sử dụng MetaTrader5 Python package trên Windows.

Nghiên cứu:

- symbol_info_tick.
- copy_ticks_from.
- copy_ticks_range.
- Bid/Ask timestamp.
- time_msc.
- flags.
- Polling interval.
- Batch recovery.
- CPU usage.
- Tick coverage.
- Disconnect/reconnect.

Polling chỉ được coi là một phương án kỹ thuật, không được mặc định nhanh hoặc chậm hơn EA khi chưa đo.

Không dùng vòng while cực nhanh tiêu thụ CPU không kiểm soát.

Không gọi nhiều thao tác terminal song song nếu chưa chứng minh tính an toàn.

## Mode B: MQL5 Event-Driven Tick Bridge

Tạo một Expert Advisor chỉ đọc, ví dụ:

`XAUUSD_TickBridge.mq5`

Nhiệm vụ của EA:

- Gắn vào chart XAUUSD.
- Nhận NewTick event.
- Đọc giá bằng SymbolInfoTick.
- Đẩy dữ liệu vào bộ đệm nhẹ.
- Gửi dữ liệu sang local streaming gateway.
- Theo dõi sequence/cursor.
- Khôi phục tick bị bỏ qua bằng CopyTicks.
- Ghi nhận tình trạng thiếu dữ liệu.
- Phát hiện kết nối lỗi.
- Reconnect có backoff.
- Không gửi bất kỳ trade request nào.

Đặc biệt lưu ý:

**OnTick không bảo đảm callback cho từng tick riêng biệt.**

Vì vậy, thiết kế phải sử dụng CopyTicks reconciliation dựa trên cursor thực tế để hạn chế thiếu dữ liệu.

Phải xử lý trường hợp nhiều tick có cùng time_msc.

Không được loại bỏ tick chỉ vì timestamp trùng mà chưa có quy tắc phân biệt sự kiện.

Nếu API không cung cấp danh tính duy nhất của tick, phải ghi nhận giới hạn này và báo cáo độ tin cậy của quá trình reconciliation.

## 3.1. Transport

Ưu tiên thử nghiệm local TCP socket trên 127.0.0.1.

Thiết kế:

- Persistent connection.
- Binary protocol hoặc MessagePack nếu có lợi ích đo được.
- Length-prefixed framing.
- Protocol version.
- Source ID.
- Sequence number.
- Bid.
- Ask.
- Last nếu được cung cấp.
- Volume/tick volume nếu có.
- Tick flags.
- Tick timestamp.
- Bridge timestamp.
- Checksums khi phù hợp.
- Heartbeat.
- Gap detection.
- Reconnect recovery.
- Bounded queue.
- Backpressure metrics.

Không gửi HTTP request đồng bộ cho từng tick nếu gây chặn OnTick.

So sánh phương án gửi trực tiếp với phương án buffer rồi flush bằng timer.

Đo cả latency và tick coverage.

Không tối ưu latency bằng cách âm thầm bỏ dữ liệu.

MQL5 networking yêu cầu cấu hình danh sách địa chỉ được phép. Viết hướng dẫn cấu hình thủ công rõ ràng.

## 3.2. Tick Data Contract

Thiết kế schema canonical:

```text
source_id
broker_server
symbol
time_msc
bid
ask
last
volume
flags
bridge_seq
bridge_received_at
gateway_received_at
quality_flags
```

Bảo toàn timestamp nguồn.

Không dùng thời gian nhận tại Python thay thế thời gian tick từ terminal.

Tính spread từ Bid/Ask thực tế.

Kiểm tra decimal precision và symbol digits/point/tick_size.

## 3.3. Không mất dữ liệu khi gián đoạn

Triển khai:

- Gap detection.
- Historical tick reconciliation.
- Startup catch-up.
- Controlled buffer.
- Duplicate handling.
- Out-of-order detection.
- Source provenance.
- Recovery checkpoints.

Nếu không thể tái tạo đầy đủ tick đã thiếu, đánh dấu `DATA_GAP_UNRECOVERABLE`.

Không im lặng bỏ qua.

---

# 4. REAL-TIME M1 CANDLE ENGINE

Phát triển Candle Engine theo hướng tick-driven.

Hỗ trợ:

- M1.
- M5.
- M15.
- H1.
- H4.

M1 là ưu tiên cao nhất.

Nến cần có:

- Time bucket.
- Open.
- High.
- Low.
- Close.
- Tick volume.
- Spread statistics.
- State OPEN/CLOSED.
- Data source.
- Completeness status.
- Last update timestamp.

Phải định nghĩa rõ loại giá dùng dựng nến:

- Bid.
- Ask.
- Mid.
- Broker-provided OHLC.

Không trộn các loại giá rồi so sánh trực tiếp.

Mặc định ưu tiên dùng một định nghĩa giá tương thích dữ liệu chart MT5 thực tế, và chứng minh điều đó bằng candle parity tests.

Nếu tick mới đầu tiên đến sau ranh giới phút, không tự tạo một tick giả tại đúng giây 00.

Không dùng giá của phút tương lai để hoàn thiện nến quá khứ.

Phải so sánh OHLC do Candle Engine tổng hợp với MT5 historical bars.

Nếu xuất hiện bar bất thường như spread bằng 0, volume rất lớn, OHLC khớp phiên kế tiếp, đặc biệt tại thời điểm rollover, phải đưa vào Data Quality Quarantine để điều tra.

Không tự động xóa mọi bar tại rollover vì có thể loại bỏ dữ liệu hợp lệ.

Phân biệt:

- Live forming candle.
- Closed candle.
- Missing candle.
- Reconstructed candle.
- Suspect candle.

Không dùng reconstructed hoặc suspect candle để xác nhận giao dịch khi chưa qua chính sách chất lượng dữ liệu.

---

# 5. LATENCY ENGINEERING & BENCHMARK

Mục tiêu là tối thiểu hóa độ trễ có thể kiểm soát, chứ không hứa hẹn đồng bộ tuyệt đối với màn hình MT5.

Đo các giai đoạn:

1. Tick timestamp from source.
2. Arrival at terminal/EA observation point.
3. EA buffer/serialization.
4. Local transport.
5. Python Gateway receipt.
6. Feature update.
7. Strategy Decision.
8. WebSocket publication.
9. Browser receive.
10. UI rendering.

Dùng monotonic clock để đo các khoảng thời gian trên cùng máy.

Khi đo qua nhiều máy, yêu cầu đồng bộ clock và công bố sai số clock; không trừ trực tiếp timestamp giữa các máy chưa đồng bộ.

## Benchmark

Đo:

- p50 latency.
- p95 latency.
- p99 latency.
- Maximum observed latency.
- Tick coverage.
- Gap count.
- Queue depth.
- CPU.
- RAM.
- Recovery time.
- UI frame consistency.

Thiết lập SLO mục tiêu ban đầu để thử nghiệm, ví dụ:

- Local tick-to-dashboard p95: mục tiêu nghiên cứu dưới 150 ms.
- Strategy hot-path p95: mục tiêu nghiên cứu dưới 50 ms.
- Không chấp nhận phát tín hiệu từ dữ liệu vượt freshness threshold được cấu hình.
- Không có sự kiện khôi phục dữ liệu bị che giấu.

Những con số này chỉ là mục tiêu thiết kế thử nghiệm, không được tuyên bố đã đạt trước khi benchmark.

Thực hiện so sánh Mode A và Mode B trên cùng nguồn MT5, cùng điều kiện, cùng thời gian đo.

Không lựa chọn Mode B chỉ vì kiến trúc nghe có vẻ nhanh hơn.

## Performance Architecture

Hot path chỉ gồm:

Tick → Data Validation → Incremental Features → State Update → Publish.

Không thực hiện trong hot path:

- Full historical recalculation.
- ML model training.
- Large database queries.
- Blocking file writes.
- Heavy logging serialization.
- Full dashboard redraw.

Dùng incremental updates, bounded queues và tách worker.

Nếu không theo kịp tick rate, hệ thống phải hiển thị overload/stale thay vì tạo tín hiệu từ dữ liệu cũ.

---

# 6. UNIFIED TRADING INTELLIGENCE RULEBOOK V3

Áp dụng toàn bộ 12 bài học đã thống nhất.

Bài 57: Pullback.

Bài 62: EMA20/50/100/200.

Bài 63: RSI Momentum.

Bài 64: RSI70 Context.

Bài 65: MACD.

Bài 66: ATR.

Bài 69: Minimal Indicator Strategy.

Bài 70: Complete Strategy.

Bài 71: Entry.

Bài 72: Confirmation.

Bài 73: No Setup.

Bài 74: Full Trading Setup.

Chiến lược chính:

`Multi-Timeframe Trend Pullback + Price Action Confirmation + Risk-Controlled Entry`

Thiết kế các engine sau.

## 6.1. Market Structure Engine

Nhận diện:

- HH/HL/LH/LL.
- Swing high/low.
- BOS.
- CHoCH.
- Support/Resistance.
- Breakout.
- Failed Breakout.
- Liquidity Sweep Candidate.

Mọi pivot phải lưu `formed_at` và `known_at`.

Không cho phép future leakage.

## 6.2. EMA Feature Engine

Tính:

- EMA20.
- EMA50.
- EMA100.
- EMA200.
- EMA slope.
- EMA separation.
- EMA compression.
- Distance to EMA normalized by ATR.

Không mặc định EMA50 tạo lệnh BUY.

## 6.3. RSI Engine

Tính RSI14 và nghiên cứu:

- RSI regime.
- Momentum shift.
- RSI divergence.
- RSI during pullback.

Không tự SELL khi RSI > 70.

Không tự BUY khi RSI < 30.

## 6.4. MACD Engine

Tính:

- MACD12/26/9.
- Signal.
- Histogram.
- Momentum change.
- Divergence candidate.

Không phát lệnh chỉ vì MACD giao cắt.

## 6.5. ATR Engine

Tính:

- ATR14.
- Volatility regime.
- ATR percentile.
- Spread/ATR.
- Stop distance context.

ATR không được sử dụng làm chỉ báo hướng giá.

## 6.6. Pullback Engine

Theo dõi:

- Pullback initiation.
- Pullback depth.
- Pullback to relevant zone.
- Price rejection.
- Continuation candidate.
- Reversal candidate.
- Failed pullback.
- Structure invalidation.

## 6.7. Confirmation Engine

Hỗ trợ:

- Pin Bar.
- Engulfing.
- Strong Close.
- Rejection.
- Structure Break.
- Breakout-Retest.
- Failed Breakout.

Phải kiểm chứng từng loại bằng timestamp, trạng thái đóng nến và điều kiện hết hiệu lực.

## 6.8. Entry Intelligence

Xác định:

- Planned Entry.
- Entry Window.
- Entry Eligible.
- Entry Missed.
- Entry Expired.
- Entry Invalidated.
- Confirmation Age.
- Maximum Chase Distance.
- Remaining R:R.

## 6.9. Decision Engine

Trả về:

- BUY.
- SELL.
- WAIT.
- BLOCKED.

Các trạng thái MISSED, EXPIRED, INVALIDATED được theo dõi riêng.

Phân biệt ba lớp nguyên nhân:

- Market reason.
- Strategy reason.
- Risk/Execution reason.

Không cho risk gate che giấu nguyên nhân setup chưa hình thành.

---

# 7. ML SHADOW BRAIN

ML phải là bộ phận nghiên cứu độc lập.

Các bài toán:

- Market Regime Classification.
- Pullback Continuation Probability.
- Reversal Risk.
- Confirmation Success.
- Probability of TP Before SL.
- Expected Net R.
- Setup Quality.

Ưu tiên baseline đơn giản:

- Logistic Regression.
- LightGBM.
- XGBoost.
- CatBoost khi phù hợp.

Không mặc định Deep Learning hoặc Reinforcement Learning tốt hơn.

Có thể nghiên cứu các nguồn mở:

- pandas-ta-classic.
- smart-money-concepts, chỉ dùng sau causal audit.
- Freqtrade lookahead analysis, tham khảo phương pháp.
- NautilusTrader, tham khảo kiến trúc.
- Qlib, tham khảo ML workflow.
- aiomql, tham khảo kết nối MT5.

Kiểm tra license và mã nguồn trước khi dùng.

ML không được chặn tick streaming.

ML training chạy riêng.

Inference phải có deadline. Nếu trễ, sử dụng trạng thái `ML_UNAVAILABLE` và giữ nguyên kết quả Rule Engine.

Không tự tạo xác suất thắng.

---

# 8. BACKTEST & HISTORICAL REPLAY

Thiết kế deterministic historical replay.

Chạy các nghiên cứu:

C0: Baseline đơn giản được chốt trước.

C1: EMA50 + RSI14 + ATR14.

C2: C1 + Market Structure.

C3: C2 + Pullback.

C4: C3 + Confirmation.

C5: C4 + MACD/Extended EMA Features.

C6: C4/C5 + Entry Timing.

C7: Candidate có ML Shadow.

Không mặc định C7 tốt nhất.

Kiểm thử:

- No look-ahead.
- No repaint.
- Closed-bar correctness.
- Tick ordering.
- Bid/Ask execution.
- Spread.
- Slippage.
- Commission.
- Broker contract specifications.
- Stop Loss.
- Take Profit.
- Pending order fill simulation khi nghiên cứu.
- Missed opportunities.
- Walk-forward evaluation.
- Feature ablation.
- Probability calibration.

Dữ liệu lịch sử phải có metadata:

- Server.
- Symbol.
- Timeframe.
- Source.
- Collection interval.
- Completeness.
- Quality flags.
- Dataset version.

Không dùng dữ liệu từ broker khác để tuyên bố kết quả sẽ lặp lại trên MetaQuotes-Demo hoặc FTMO.

---

# 9. RISK MANAGEMENT

Hệ thống chỉ tính kế hoạch và mô phỏng, chưa giao dịch thật.

Yêu cầu:

- Account equity tham khảo.
- Risk fraction cấu hình.
- Structural Stop Loss.
- ATR buffer nếu được chiến lược sử dụng.
- Take Profit.
- Reward/Risk.
- Estimated loss.
- Estimated lot.
- Broker volume_min/max/step.
- Spread.
- Slippage allowance.
- Account-level risk.

Nếu mức lot tối thiểu vượt ngân sách rủi ro thì BLOCKED.

Nếu có chính sách FTMO, phải lấy đúng chương trình và thời điểm hiệu lực từ cấu hình đã kiểm chứng.

Không hardcode các giới hạn FTMO.

---

# 10. REAL-TIME TRADING DASHBOARD

Xây dựng frontend chuyên nghiệp, ưu tiên desktop.

Tech stack đề xuất:

- Next.js App Router.
- TypeScript strict.
- Tailwind CSS.
- Lightweight Charts hoặc thư viện tương đương phù hợp license.
- WebSocket streaming.
- Python FastAPI backend.

## Layout

### A. Live Chart

- XAU/USD M1 candlestick.
- M5/M15/H1/H4 selector.
- Real-time price.
- Bid/Ask.
- Spread.
- EMA20/50/100/200.
- Support/Resistance.
- Swing points.
- BOS/CHoCH.
- Pullback zones.
- Entry/SL/TP.
- Signal annotations.

### B. Market Intelligence

- Trend.
- Market Regime.
- Volatility Regime.
- Market Structure.
- RSI.
- MACD.
- ATR.

### C. Setup Intelligence

- Current setup.
- Direction.
- Setup phase.
- Confirmation status.
- Missing evidence.
- Entry readiness.
- Invalidation.
- Expiration.

### D. Decision Intelligence

- BUY / SELL / WAIT / BLOCKED.
- Primary reason.
- All reasons.
- Next required event.
- Confidence only if validated.
- Strategy version.

### E. Data Quality & Latency

Hiển thị:

- MT5 connection status.
- Broker server identifier.
- Last tick time.
- Last received time.
- Tick ingestion rate.
- Gap count.
- Queue backlog.
- p50/p95/p99 latency.
- Data freshness.
- Reconnect status.

Không giấu lỗi dữ liệu dưới nhãn Connected.

Nếu dashboard mất kết nối phải hiện STALE/DISCONNECTED rõ ràng.

Không tạo giả nến bằng cách lặp giá cuối khi không có tick.

### F. Audit & Research

- Setup timeline.
- Rule execution trace.
- Historical replay.
- Candidate comparison.
- Decision logs.
- Strategy metrics.

## UX Performance

- Không render lại toàn bộ chart sau mỗi tick.
- Chỉ cập nhật nến đang hình thành.
- Chỉ cập nhật indicator cần thiết.
- Sử dụng subscriptions và memoization hợp lý.
- Điều tiết tốc độ vẽ nhưng không tự ý làm mất dữ liệu giá.
- Tách ingestion fidelity khỏi UI frame rate.

Mục tiêu là giao diện phản ứng mượt trên Windows desktop và MacBook M1.

---

# 11. CROSS-PLATFORM NETWORK & SECURITY

Ưu tiên chạy toàn bộ hot path trên Windows cùng MT5.

MacBook M1 truy cập dashboard qua LAN hoặc VPN riêng như WireGuard/Tailscale nếu được cấu hình.

Không mở trực tiếp cổng MT5 bridge ra public internet.

Thiết kế:

- Local-only bridge binding.
- Dashboard authentication.
- Read-only API authorization.
- Secure remote access.
- No credentials in frontend.
- No secrets in Git.
- Restricted CORS.
- Network firewall policy.
- Optional TLS reverse proxy.
- Audit logs.

Nếu Windows mất kết nối, Mac không được tự tạo hoặc dùng lại dữ liệu cũ như dữ liệu real-time.

Nếu thử chuyển nguồn sang MT5/Wine trên Mac, phải coi đó là failover có kiểm chứng, có quyền nguồn dữ liệu duy nhất và chống nhân đôi các sự kiện. Không gộp hai broker feed khác nhau.

---

# 12. STORAGE & OBSERVABILITY

Thiết kế hệ thống lưu trữ nhẹ trước, chỉ tăng độ phức tạp khi benchmark chứng minh cần thiết.

Các lớp dữ liệu:

- Tick history: partitioned Parquet hoặc định dạng phù hợp.
- Candle history.
- Setup events.
- Decision logs.
- Strategy configurations.
- Backtest results.
- ML experiments.
- Latency measurements.

Có thể sử dụng SQLite WAL cho metadata/event logs cục bộ, hoặc database khác nếu concurrency yêu cầu.

Không thực hiện blocking disk writes trong OnTick hot path.

Thiết kế retention policy và recovery.

Logs có correlation ID, setup ID, source ID, timestamps, reason code và strategy version.

---

# 13. BUILD PLAN & IMPLEMENTATION PHASES

Bạn phải trực tiếp triển khai theo trình tự phụ thuộc kỹ thuật.

## PHASE 0: PRE-FLIGHT & REPOSITORY DISCOVERY

Kiểm tra folder, toolchain, MT5 terminal, Python package, OS, symbol và quyền truy cập.

Tạo:

- ENVIRONMENT_AUDIT.md
- ARCHITECTURE_DECISION.md
- CONNECTIVITY_MATRIX.md

Không tạo báo cáo PASS giả.

## PHASE 1: LIVE DATA CONNECTION

Triển khai:

- Native Python MT5 connector.
- Minimal MQL5 Tick Bridge.
- TCP streaming gateway.
- Tick schema.
- Terminal health monitoring.
- Connection recovery.
- Benchmark A/B.

Đầu ra bắt buộc: ứng dụng có thể hiển thị Bid/Ask XAUUSD thực từ MT5, hoặc báo chính xác blocker nếu terminal không truy cập được.

## PHASE 2: M1 CANDLE & MULTI-TIMEFRAME ENGINE

- Tick aggregation.
- Closed-bar semantics.
- MT5 candle parity.
- Gap detection.
- Multi-timeframe aggregation.
- Persistent history.

## PHASE 3: UNIFIED STRATEGY ENGINE

Triển khai toàn bộ 12 bài học:

- EMA.
- RSI.
- MACD.
- ATR.
- Market Structure.
- Zones.
- Pullback.
- Confirmation.
- Entry.
- Risk.
- BUY/SELL/WAIT taxonomy.

Ưu tiên Rule Engine giải thích được trước khi huấn luyện ML.

## PHASE 4: REAL-TIME DASHBOARD

Triển khai biểu đồ, overlay, setup state, decision panel và latency panel.

Không chỉ trình diễn mock price.

## PHASE 5: HISTORICAL REPLAY & QUANT VALIDATION

- Dataset QA.
- Look-ahead audit.
- Replay.
- Backtest.
- Candidate comparison.
- Walk-forward.

## PHASE 6: ML SHADOW

- Feature datasets.
- Labels.
- Baseline ML.
- Calibration.
- Model evaluation.
- Shadow predictions.

## PHASE 7: CROSS-PLATFORM QA

- Windows host.
- MacBook browser client.
- Network disconnect.
- Sleep/resume.
- Reconnect.
- Performance.
- Data parity.

Không đánh dấu Mac testing là PASS nếu chưa thực sự chạy trên thiết bị Mac.

---

# 14. TEST MATRIX & ACCEPTANCE CRITERIA

## Data Tests

- XAUUSD symbol discovered correctly.
- Bid <= Ask dưới điều kiện quote bình thường; dữ liệu bất thường phải được flag thay vì âm thầm sửa.
- UTC handling.
- Tick sequence reconciliation.
- Duplicate handling.
- Gap recovery.
- Out-of-order events.
- Startup catch-up.
- Disconnect/reconnect.
- M1 candle parity.
- Suspicious rollover bars.
- Closed-bar confirmation.

## Strategy Tests

- RSI > 70 không tự SELL.
- RSI < 30 không tự BUY.
- EMA crossover không tự kích hoạt lệnh.
- ATR cao không tự BUY.
- Pullback chưa xác nhận tạo WAIT.
- Invalidated setup không phát Entry.
- Entry hết hạn không được chase.
- Risk Gate không bị bypass.
- Reason codes nhất quán.

## Performance Tests

- Burst tick ingestion.
- Sustained tick processing.
- Memory leak monitoring.
- Queue saturation.
- Latency percentile.
- UI frame performance.
- M1 rollover.
- MT5 disconnected state.

## Safety Tests

- No order_send.
- No live execution.
- No public bridge port.
- No secrets in repository.
- No misleading connected status.
- No false completed tests.
- No baseline mutation.
- No ML live execution.

---

# 15. REQUIRED REPOSITORY STRUCTURE

Đề xuất cấu trúc sau, được phép cải tiến sau audit:

```text
261013-ML-XAUUSD/
  README.md
  CLAUDE.md
  .env.example
  .gitignore

  apps/
    dashboard/

  services/
    gateway/
    intelligence/
    research/

  mt5/
    experts/
    include/
    scripts/

  packages/
    contracts/
    strategy_rules/

  data/
    README.md

  tests/
    unit/
    integration/
    replay/
    performance/

  benchmarks/

  configs/
    strategy/
    risk/

  docs/
    architecture/
    research/
    runbooks/
    qa/

  scripts/
    windows/
    macos/
```

Không bắt buộc duy trì cấu trúc trên nếu repo đã có kiến trúc tốt hơn.

Không commit dữ liệu lớn, credentials, account tokens hoặc file môi trường bí mật.

---

# 16. REQUIRED DELIVERABLES

Tạo tối thiểu:

1. Working source code.
2. MQL5 EA read-only source.
3. Windows MT5 connectivity adapter.
4. Low-latency benchmark script.
5. Real-time M1 candle engine.
6. Multi-timeframe indicators.
7. Unified Trading Rulebook implementation.
8. Setup State Machine.
9. Risk/Entry Intelligence.
10. WebSocket API.
11. Dashboard.
12. Historical replay.
13. Automated tests.
14. Windows installation guide.
15. MacBook M1 access/development guide.
16. Security guide.
17. Data integrity report.
18. Benchmark report.
19. Backtest report nếu có dữ liệu hợp lệ.
20. Known limitations and next steps.

Tài liệu phải chứa hướng dẫn chạy chính xác bằng PowerShell trên Windows và terminal trên macOS cho các thành phần tương ứng.

README phải giúp một người có MT5 đang chạy có thể khởi động ứng dụng mà không cần đọc toàn bộ source code.

---

# 17. AUTONOMOUS EXECUTION INSTRUCTIONS

Bạn là Claude Code hoạt động trực tiếp trong workspace.

Không chỉ viết kế hoạch rồi dừng.

Thực hiện:

DISCOVER → DESIGN → IMPLEMENT → TEST → BENCHMARK → DOCUMENT.

Phải chủ động đọc file, tìm lỗi, chạy test, sửa mã và tự kiểm tra kết quả.

Không đặt câu hỏi cho những vấn đề có thể giải quyết bằng cách kiểm tra môi trường hoặc chọn mặc định kỹ thuật an toàn.

Nếu gặp blocker thực sự, báo cáo chính xác:

- Blocker là gì.
- Bằng chứng.
- Đã thử những gì.
- Phần nào đã hoàn thành.
- Lệnh hoặc thao tác cần người dùng thực hiện.

Không tự ý nhập password, thay đổi tài khoản MT5 hoặc bật live trading.

Không xóa dữ liệu người dùng.

Không giả mạo quá trình test.

Không tự động clone hàng loạt repository không cần thiết.

Ưu tiên code có mục tiêu, tái sử dụng thư viện đã kiểm chứng và giữ dependency footprint hợp lý.

Mỗi phase phải có acceptance criteria trước khi chuyển sang phase tiếp theo.

Nếu Phase 1 chưa kết nối thành công MT5, có thể xây dựng module độc lập và test bằng fixture có nhãn rõ ràng, nhưng không được tuyên bố ứng dụng đã chạy real-time.

---

# 18. FIRST EXECUTION INSTRUCTION

Hãy bắt đầu NGAY bằng:

1. Kiểm tra nội dung thực tế của workspace hiện tại.
2. Phát hiện Windows 11, Python, Node, Git và MT5.
3. Xác định phương án kết nối chính thức MetaTrader5 Python có hoạt động không.
4. Xác định symbol XAUUSD và server thực tế từ terminal, không hardcode.
5. Thiết kế benchmark so sánh Python polling với MQL5 Tick Bridge.
6. Triển khai Vertical Slice đầu tiên:

**MT5 Real Tick → Gateway → M1 Candle → WebSocket → Live Dashboard.**

7. Chứng minh dữ liệu dashboard có nguồn gốc từ terminal thật.
8. Đo độ trễ.
9. Sau đó tiếp tục triển khai Strategy Engine theo Rulebook V3.

Thứ tự ưu tiên:

**DATA INTEGRITY > EXECUTION SAFETY > CORRECTNESS > LATENCY > STRATEGY QUALITY > UI COMPLEXITY.**

Không được đánh đổi tính đúng đắn dữ liệu để có chỉ số latency đẹp.

# FINAL SUCCESS DEFINITION

Dự án chỉ được coi là đạt giai đoạn nền tảng khi:

- Kết nối MT5 thật thành công.
- Dữ liệu giá có provenance.
- Biểu đồ M1 cập nhật từ tick.
- Có benchmark latency đo được.
- Có Data Quality & Gap Detection.
- Có dữ liệu đa khung thời gian hợp lệ.
- Có BUY/SELL/WAIT Rule Engine giải thích được.
- Có Entry và Risk Intelligence.
- Có Historical Replay.
- Có automated tests.
- Có dashboard sử dụng được trên Windows và trình duyệt MacBook.
- Không có đường đặt lệnh thật trong Candidate.
- Các giới hạn chưa đạt được được công bố trung thực.

**Bắt đầu xây dựng và kiểm thử trong workspace hiện tại. Không dừng ở việc đưa ra danh sách đề xuất.**