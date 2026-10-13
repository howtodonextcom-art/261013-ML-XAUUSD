# CLAUDE.md — quy tắc dự án 261013-ML-XAUUSD

## Git identity (bắt buộc)
Commit author và committer bắt buộc: `howtodonext.com <howtodonext.com@gmail.com>`.
Không dùng email/tên Git local khác. Vercel kiểm tra identity; sai email sẽ bị bắt bẻ / deploy lệch tài khoản.

Đặt theo từng commit (KHÔNG dùng `git config --global`):

```bash
GIT_AUTHOR_NAME="howtodonext.com" \
GIT_AUTHOR_EMAIL="howtodonext.com@gmail.com" \
GIT_COMMITTER_NAME="howtodonext.com" \
GIT_COMMITTER_EMAIL="howtodonext.com@gmail.com" \
git commit ...
```

Trước khi push, kiểm tra `git log --format='%an <%ae> | %cn <%ce>'`: mọi commit phải đúng identity trên.

## Branch & push
- Push tất cả lên `main`. Không tách nhánh feature.
- Remote: https://github.com/howtodonextcom-art/261013-ML-XAUUSD
- Không force push, không đổi remote ngoài URL trên.

## An toàn giao dịch
- Chế độ mặc định: `READ_ONLY + SHADOW + PAPER_SIMULATION`. Không gọi hàm đặt/sửa/hủy lệnh (`order_send`, `OrderSend`, ...).
- Luôn chỉ định đường dẫn terminal MT5 cụ thể (máy có cả MetaQuotes-Demo và FTMO).

## Không commit
`.venv/`, `data/store/`, `configs/source.json` (chứa tham chiếu tài khoản), `.env`, thư mục `image/` của người dùng nếu chưa được yêu cầu.
