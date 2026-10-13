---
id: project1-app-protocol-focus
type: preference
scope: project:project1_app
status: confirmed
source: sessions/2026-10-09-menu-crc-image-cache.md
valid_from: 2026-10-09
updated: 2026-10-09
supersedes: ""
---

Khi thiết kế tính năng đồng bộ app ↔ server ↔ máy trong `project1_app`, user quan tâm đến **giao thức và hợp đồng gói tin** (route, body, lệnh máy, kết quả, giới hạn). Phần triển khai phía máy (`version1.1/machine`) không thuộc phạm vi nếu user không yêu cầu.

User nói: "version1.1 là phía machine, tôi không quan tâm, cái tôi quan tâm là giao thức để cập nhật gói tin thôi".

Cách áp dụng:
- Đặc tả gói tin rõ ràng, rồi làm server và app.
- Ghi rõ phía máy cần gì để khớp, nhưng không tự sửa code máy.
- Test phía máy bằng máy giả, hoặc chạy code máy thật mà không sửa nó.
