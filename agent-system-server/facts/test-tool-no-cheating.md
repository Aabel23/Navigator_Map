---
id: test-tool-no-cheating
type: preference
scope: project:project1_app
status: confirmed
source: sessions/2026-10-09-menu-crc-image-cache.md
valid_from: 2026-10-09
updated: 2026-10-09
supersedes: ""
---

Tool test luồng (module dùng lại về sau) theo mẫu user yêu cầu với `tests/tools/menu_crc_stress/`:

1. **Bên luồng chạy code hiện tại thật, không gian lận.**
   - Server thật và relay thật.
   - Code máy thật.
   - Quyền lấy qua luồng thật, ví dụ manager có qua `share/create` + `share/accept`.
2. **Bên oracle tự tính bằng hàm riêng.** Không import code sản phẩm, không dùng lại cùng hàm (ví dụ CRC32 viết bằng bảng thuần Python thay vì `zlib`).
3. Lặp vài trăm thay đổi ngẫu nhiên có seed, ở đúng cấp quyền (quản lý), rồi **trả về trạng thái gốc**.
4. **Thống kê pass/fail** cho từng kiểm tra.

Bài học kèm theo (agent rút ra, đã kiểm trong phiên):
- Phải chạy thử **sabotage**: cố ý làm hỏng code sản phẩm trong một bản nháp, rồi xác nhận tool báo FAIL.
- Lần đầu, sabotage "update trả ok nhưng không ghi DB" vẫn PASS. Phải thêm kiểm tra `update_applied` mới bắt được.
