---
name: plan-live-checklist
description: Dựng trang plan live (tự tải lại khi lưu Markdown) kèm checklist từng bước chưa làm/đang làm/đã làm, quy tắc đánh dấu ghi trong md cho agent.
source: sessions/2026-10-08-plan-live-checklist.md
status: extracted
reference_impl: ~/project/internproj/project1_server/internal/plan/cong_cu/theo_doi_plan.py
---

# Trang plan live + checklist thực thi

## Khi dùng
User có plan dạng Markdown/HTML và muốn "stream lên port N để xem live", "thêm checklist đang làm/chưa làm/đã làm", "ghi rule xuống md".

## Thiết kế đã được chấp nhận
- **Một script Python stdlib** (không thêm dependency): `ThreadingHTTPServer`, mặc định `127.0.0.1:<port>`, `--host 0.0.0.0` cho LAN.
- **Nguồn chuẩn là Markdown.** Checklist ở `checklist.md`: phần đầu là *Quy tắc*, dưới heading `## Checklist` là các bảng `| Bước | Trạng thái | Ngày | Ghi chú |` theo khối. Script chỉ đọc bảng dưới heading đó.
- **Ba chữ trạng thái cố định**: `chưa làm` ○, `đang làm` →, `đã làm` ✓. `đang làm`/`đã làm` bắt buộc ngày; `đã làm` bắt buộc bằng chứng.
- **Danh sách bước lấy từ plan**, không chép tay: parse ID bước từ file plan (cùng regex với bộ dựng HTML sẵn có). `--sync` viết lại bảng theo thứ tự plan, giữ trạng thái/ghi chú cũ, chuyển bước đã bỏ xuống "Không còn trong plan".
- `--check` (và một test pytest) đỏ khi: sai chữ trạng thái, thiếu ngày, thiếu bằng chứng, lặp, lệch plan.
- **Trang live**: lấy HTML plan có sẵn (dựng ra file tạm nếu có bộ dựng, không ghi đè bản trong repo), chèn mục Checklist (thanh tiến độ, nút lọc, khung "Đang thực thi", bảng theo khối) và dấu trạng thái vào từng ô bước. Dùng lại CSS token của trang.
- **Tự cập nhật**: thread poll mtime/size các file plan → chữ ký; endpoint SSE `/events` đẩy chữ ký; client so với chữ ký nhúng trong trang, khác thì reload và giữ vị trí cuộn.
- **An toàn**: chỉ phục vụ file trong thư mục tài liệu (allowlist, `resolve()` + `is_relative_to`), `.md` trả `text/plain`. Escape mọi text; link chỉ cho tương đối/http(s).
- **Cổng bận**: bắt `EADDRINUSE`, in hướng dẫn (`ss -ltnp`, `--port N+1`) thay vì traceback.
- Không có `node` trên PATH: thử Node của VS Code server; không có thì dùng HTML dựng sẵn và ghi chú trên trang.

## Quy tắc md nên ghi (rút gọn)
Bắt đầu bước → `đang làm` + ngày, trước khi sửa code · phép kiểm đạt → `đã làm` + bằng chứng · bị chặn/chờ user → giữ `đang làm`, ghi `✗`/`⏸ Qn` · hồi quy → quay về `đang làm` · agent chỉ sửa dòng khối mình · không thêm/xoá dòng tay, dùng `--sync` · bước `đã làm` ≠ khối xong · chạy `--check` sau khi sửa. Thêm một dòng bắt buộc vào `AGENTS.md`.

## Kiểm trước khi bàn giao
`--check` hợp lệ; pytest đạt; curl trang + file tĩnh + path traversal → 404; SSE đổi chữ ký khi `touch`; chụp headless (`google-chrome --headless=new --timeout=4000 --screenshot`, **không** dùng `--virtual-time-budget` vì SSE giữ trang mở) ở desktop và 390px; bộ kiểm cũ của trang plan vẫn đạt.
**Tắt server chạy nền trước khi bàn giao** — user sẽ tự chạy trên đúng cổng đó.

## Seed trạng thái
Điền từ file bằng chứng hiện có, bảo thủ (đạt trên dev nhưng còn môi trường phải kiểm = `đang làm`), ghi nguồn trong ghi chú, và báo user duyệt lại.
