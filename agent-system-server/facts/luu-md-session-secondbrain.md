---
id: luu-md-session-secondbrain
type: preference
scope: global
status: confirmed
source: sessions/2026-10-10-heartbeat-long-poll.md
valid_from: 2026-10-10
updated: 2026-10-10
supersedes: ""
---

Khi user viết **"lưu md"** (không kèm tên file hay tài liệu cụ thể), ý là chạy skill `/session-secondbrain`: chốt phiên vào vault. Không phải xuất tài liệu đang làm ra file `.md`.

User nói (10/10/2026): "không nhầm, ý tôi là /session-secondbrain", sau khi agent hiểu "lưu md" thành tạo bản Markdown của trang HTML.

Cách áp dụng: "lưu md" → gọi skill session-secondbrain. Nếu user nói rõ "lưu bản md của <tài liệu>" thì mới xuất file.
