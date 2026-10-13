---
id: document-shared-assets
type: preference
scope: global
status: confirmed
source: current-conversation, user chốt 2026-10-13
valid_from: 2026-10-13
updated: 2026-10-13
supersedes: ""
---
Khi khởi tạo một bộ document, tạo thư mục `assets/` ngay trong thư mục gốc của bộ tài liệu (ví dụ `documentation/assets/`). Đặt CSS, JavaScript và font dùng chung tại đó; các trang trong bộ tài liệu liên kết bằng đường dẫn tương đối tới cùng asset. Font phải được đóng gói cục bộ để tài liệu hiển thị đúng khi không tải được Google Fonts hoặc khi mở offline. Không đặt asset chung bên trong một nhánh con như `architect/` rồi để các nhánh khác trỏ vòng qua đó.

Quy tắc này được user nói rõ khi yêu cầu sửa font cho `project1_app` ngày 13/10/2026. Ví dụ đã triển khai: `/home/abel/project/internproj/project1_app/documentation/assets/` và `documentation/assets/README.md`. Vẫn áp dụng chuẩn trình bày tại [[document-framework/manual/STANDARD]].
