---
id: project1-app-auth-identity-confirmed
type: decision
scope: project:project1_app
status: confirmed
source: sessions/2026-10-11-app-endpoints-auth-research.md
valid_from: 2026-10-11
updated: 2026-10-12
supersedes: ""
---

Quyết định user chốt về tài khoản, đăng nhập và danh tính cho hệ IoT v1.1 (bổ sung [project1-app-v11-iot-design-confirmed](project1-app-v11-iot-design-confirmed.md)):

- **Đăng nhập bằng email**; bỏ ô "Tên đăng nhập" trên app.
- **Mật khẩu tối thiểu 8 ký tự, không ràng buộc gì thêm** (user chọn, dù NIST 800-63B bản 4 đòi 15 khi chỉ có mật khẩu; doc ghi rõ là lệch chuẩn có chủ đích).
- **Đăng ký trả câu trung tính** (chống dò email), kèm nút "Sai email? Quay lại".
- **Access token 1 giờ, refresh token trượt 30 ngày.**
- **Nhập lại mật khẩu** cho: chuyển chủ, khoá máy, gỡ máy, đổi mật khẩu.
- **Mất email = mất tài khoản** (MVP không có đổi email hay kênh khôi phục khác).
- **Lệnh qua LAN/Bluetooth phải được mã hoá**, không chỉ ký. Hệ quả agent nêu, user không phản đối: máy cần cặp khoá riêng; kênh mã hoá giống nhau trên cả ba đường; khi đi qua server, server chỉ kiểm quyền theo loại lệnh ở phần ngoài gói.
- **Danh tính điện thoại = cặp khoá sinh trong Android Keystore**; server ghi khoá công khai; server ký "bản quyền" cho từng máy; máy kiểm bằng khoá công khai server; dùng chung cho cả ba đường (user trả lời "ok" cho đề xuất).
- **Bản quyền trên máy hạn 7 ngày**; hết hạn thì máy chỉ cho bán hàng và xem (user trả lời "ok" cho đề xuất).

Chi tiết và thông số còn là đề xuất: `project1_app/documentation/research/account-login-identity.html`.
