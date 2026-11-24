# AGENTS.md — ChiaBanBCR

## Bắt buộc: tự push GitHub sau mỗi lần thay đổi

Người dùng đã cho phép thường trực: **sau mỗi lần cập nhật/sửa đổi mã, tự chạy push lên
GitHub, không cần hỏi lại.**

```
powershell -ExecutionPolicy Bypass -File .\push_update.ps1 "mô tả thay đổi"
```

- Remote: `https://github.com/vzetiZero/bcr_chiaban.git`, nhánh `main`.
- Script chạy `git add -A` (tôn trọng `.gitignore`), commit rồi `git push origin main`.
- Phải chạy test trước khi push:

```
python -m unittest discover -s tests -t . -q
node tests/test_reader.cjs
```

- Push lỗi (mạng/xác thực) thì sửa và push lại; không để commit tồn cục bộ.
- Ngoại lệ duy nhất: người dùng nói rõ "đừng push lần này".

## Bí mật — tuyệt đối không commit

- Link bàn có `token=`, JWT, cookie, API key: không dán vào mã, README, test.
- Đã nằm trong `.gitignore`: `chrome_profile*/`, `aibcr_state*.json`,
  `aibcr_ws_frames*`, `drivers/`, `live_reports.jsonl`, `aibcr_trace.jsonl`.

## Kiến trúc

- `aibcr/` backend MVC: `models/` thuần logic, `adapters/` CDP/Selenium,
  `controllers/` điều phối, `service/` transport JSON-RPC.
- Phạm vi chỉ là **đặt cược DG (Laya)**: mở site → vào sảnh → vào bàn dùng chung →
  xếp chip → xác nhận. Không đọc kết quả, không dự đoán, không sổ lãi/lỗ.
- `ui/` Electron; renderer chỉ gọi qua `preload.js`.
- `tools/` script chạy tay. `tests/` unittest + node.
