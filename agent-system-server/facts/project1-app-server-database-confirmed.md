---
id: project1-app-server-database-confirmed
type: decision
scope: project:project1_app
status: confirmed
source: sessions/2026-10-11-server-database-research.md
valid_from: 2026-10-11
updated: 2026-10-11
supersedes: ""
---

Quyết định user chốt cho dữ liệu của server hãng v1.1 (user trả lời "ok" cho bốn khuyến nghị):

- **Server giữ bản sao nhật ký theo người**, để chủ xem khi máy mất mạng; bản gốc nằm trên máy (máy gửi lên qua hộp thư đi). Giải mâu thuẫn "nhật ký ở đâu" còn treo trong [project1-app-v11-iot-design-confirmed](project1-app-v11-iot-design-confirmed.md).
- **Quyền lưu cả lịch sử thay đổi** (ai share ai, ai đổi vai ai, lúc nào), không chỉ hiện trạng.
- **Máy offline thì server từ chối lệnh thường ngay**, app tự thử lại hoặc chuyển LAN/BT; server chỉ giữ chờ thông điệp quản trị (giấy phép share/gỡ/đổi vai, đồng bộ quyền) để giao khi máy nối lại.
- Research database ở bước này dừng ở **mô hình dữ liệu khái niệm**, chưa chọn engine (giữ cổng tầng 2).

Mô hình chi tiết (thực thể, khóa, ràng buộc) vẫn là đề xuất: `project1_app/documentation/research/server-database.html`.
