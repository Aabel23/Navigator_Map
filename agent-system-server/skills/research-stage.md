---
name: research-stage
description: Quy trình mặc định cho research stage; user nói "deep research" thì tự chia nhỏ vấn đề, cử agent researcher song song, tổng hợp, viết HTML research.
source: phiên 2026-10-11 (bảo mật hai chặng project1_app)
status: extracted
---

# Research stage

Bản chạy được nằm ở `~/.claude/skills/research-stage/` (SKILL.md, khung prompt researcher, script gắn chú thích kiểu Wikipedia, script kiểm render, bộ thuật ngữ bảo mật). Note này chỉ là con trỏ; sửa quy trình thì sửa ở SKILL.md.

Tóm tắt: hiểu đúng câu hỏi (không đoán thứ đã bàn, tìm hoặc hỏi lại) → giải thích ở mức hệ thống → ghi quyết định, dọn doc cũ có sao lưu → "deep research": tự chia nhỏ, báo mỗi agent một dòng, chạy song song Sonnet medium, prompt không có vault → kiểm lại phát hiện nghiêm trọng trong code → tổng hợp kèm câu hỏi cần user quyết → HTML trong `documentation/research/` theo chuẩn FexMix, viết như bản tiêu chuẩn, có chú thích thuật ngữ → bàn xong mới chuyển sang `documentation/architect/`.
