---
id: navigator-map-tier1-decisions
type: decision
scope: project:navigator_map
status: confirmed
source: sessions/2026-10-13-ride-hailing-system-design-tier1.md
valid_from: 2026-10-13
updated: 2026-10-13
supersedes: ""
---

User chốt ngày 13/10/2026 (tầng 1, app gọi xe kiểu Grab / Xanh SM):

1. **Mô hình đối tác**: ta cung cấp dịch vụ map và phân công việc cho tài xế đối tác.
2. **MVP chỉ gồm map + định vị + chỉ đường.** Báo giá, điều phối, chuyến đi, thanh toán bàn và làm sau; app chở người là stage xây trên nền này.
3. **Xe máy trước, ô tô sau.** Hai loại có thể độc lập; cơ chế giữa hai loại còn phải bàn; mục tiêu cuối là cả hai.
4. **Demo một quận.**
5. **`server/` hiện tại là khối Nền tảng bản đồ**, giữ nguyên ranh giới.

Chưa chốt: modular monolith hay microservice; một bản đồ nhiều hồ sơ xe; thứ tự 3D (ảnh mục tiêu Map4D) so với chỉ đường; xem note phiên.
