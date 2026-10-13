---
name: bang-agent-hoat-dong
description: Thêm bảng "Agent đang hoạt động" vào trang live — agent tự báo bằng lệnh CLI, trang hiện ai đang làm bước nào, ai im lặng quá lâu.
source: sessions/2026-10-08-plan-live-checklist.md
status: extracted
reference_impl: ~/project/internproj/project1_server/internal/plan/cong_cu/theo_doi_plan.py (read_agents, report, agents_html)
---

# Bảng quan sát agent

## Khi dùng
User chạy nhiều agent (Codex, Claude, …) trên cùng plan và muốn "một table nhỏ để quan sát agent, con nào hoạt động, làm gì".

## Thiết kế
- Không có cách tự phát hiện agent → **agent tự báo**. Nói rõ giới hạn này với user.
- Lệnh: `theo_doi_plan.py --agent <tên> --step <bước> --task "<việc>"`; xong: `--agent <tên> --idle`. Agent không sửa file tay.
- Lưu ở một file md (`agent_hoat_dong.md`): header hướng dẫn + bảng `| Agent | Trạng thái | Bước | Việc | Cập nhật |`, **mỗi agent một dòng** (upsert, dòng mới nhất lên đầu), giờ `YYYY-MM-DD HH:MM:SS`.
- Trang: chấm xanh *đang làm*; vàng *im lặng N phút* khi quá 30 phút không báo; xám *nghỉ*. Mã bước link tới dòng checklist. Tiêu đề hiện số agent đang làm. File nằm trong thư mục được theo dõi nên SSE tự đẩy cập nhật.
- Ghi quy tắc "báo khi bắt đầu, đổi việc, xong" vào `AGENTS.md`.
- Test: upsert giữ một dòng/agent, đánh dấu im lặng theo thời gian giả lập, escape nội dung.
