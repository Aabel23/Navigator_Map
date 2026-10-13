---
id: tiered-project-context
type: workflow-preference
scope: global
status: confirmed
source: current-conversation, user request on 2026-10-09
valid_from: 2026-10-09
updated: 2026-10-09
supersedes: ""
---

Ngày 09/10/2026 user yêu cầu ba việc:
- Lưu phân tích project và **tiến trình** vào vault, để mỗi lần hỏi lại agent không phải dò code và tốn token chỉ để lấy ngữ cảnh.
- Chuyển báo cáo, log, transcript của agent ra khỏi repo vào vault.
- Tách tầng, để agent chỉ mở báo cáo khi thực sự cần, không đọc hết mỗi lần được gọi.

Áp dụng cho mọi project có note trong `projects/`:

- **Tầng 1**: `projects/<nhóm>/<repo>.md`. Ngắn, chỉ gồm bảng "câu hỏi nào thì mở file nào", trạng thái một dòng và commit neo.
- **Tầng 2**: `projects/<nhóm>/<repo>/`. Gồm `STATUS.md` (tiến trình và nhật ký), `ARCHITECTURE.md`, cùng các note chủ đề. Mỗi lần chỉ mở đúng file cần.
- **Tầng 3**: `projects/<nhóm>/<repo>/archive/`. Nguyên văn báo cáo, log, transcript, có `README.md` làm catalog. Chỉ mở khi cần trích dẫn hoặc tìm bằng chứng, và dùng `rg` thay vì đọc cả file.
- Câu hỏi về tiến trình thì trả lời từ `STATUS.md` sau khi kiểm độ tươi (`git log -1` so với `anchor_commit`). Nếu lệch, chỉ đọc diff từ commit neo rồi cập nhật note.
- Báo cáo agent mới ghi vào `archive/<chủ-đề>-<ngày>/`, không ghi vào repo. Sau mỗi việc làm đổi trạng thái, cập nhật `STATUS.md` (bảng và một dòng nhật ký).

Fact này mở rộng [project-map-upkeep](project-map-upkeep.md): tiến trình **được** lưu, nhưng chỉ lưu trong `STATUS.md` kèm ngày và commit neo, không chép sang note khác.
