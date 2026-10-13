---
id: document-standard-flexmix-manual
type: design-standard
scope: global
status: confirmed
source: sessions/2026-10-09-flexmix-manual-standard.md
amended_by: sessions/2026-10-13-linux-server-and-diagram-standard.md
valid_from: 2026-10-09
updated: 2026-10-13
---

# Thiết kế chuẩn: kiểu FexMix_Munual

User chốt ngày 09/10/2026: thiết kế của `internproj/FexMix_Munual.html` là **thiết kế chuẩn**; mọi document về sau phải đạt chất lượng tương tự. File này mô tả chuẩn đó để dùng mà không cần mở lại trang gốc.

## Bộ file

| File | Dùng khi |
|---|---|
| [template.html](template.html) | Điểm bắt đầu cho mọi document mới. Giữ nguyên `<style>` và script renderer; thay nội dung khung. |
| [reference-FexMix_Munual.html](reference-FexMix_Munual.html) | Bản chụp trang chuẩn ngày 09/10/2026, để so chất lượng. Không chép nội dung FlexMix sang đề tài khác. |

Template là một fragment HTML (không có `<html>/<head>/<body>`), đúng như trang gốc. Khi khởi tạo bộ document, tạo `assets/` ở gốc bộ tài liệu để các trang dùng chung CSS, JavaScript và font cục bộ; liên kết bằng đường dẫn tương đối từ mỗi trang. Font offline là mặc định, không dựa vào Google Fonts để hiển thị đúng. Mermaid `11.4.1` trong template hiện lấy từ jsDelivr; khi không có mạng, sơ đồ có thể hiện mã nguồn. Xem [quy tắc asset dùng chung](../../facts/document-shared-assets.md).

## Khung trang

1. **Masthead**: eyebrow (loại tài liệu · dự án), H1 nói hệ thống làm gì, meta bên phải gồm nguồn + commit, ngày phân tích, quy mô.
2. **Mục 1 · Bức tranh toàn cục**: SVG vẽ tay (class `ov`), vùng (`zn`) theo tầng, khối tô theo vai trò, đường đi chính màu accent có huy hiệu số thứ tự (`bd`), chú giải (`legend`) ngay trên hình, nút Phóng to, figcaption diễn giải bằng chữ.
3. **Lưới tài liệu** (`shell`): mục lục dính bên trái ≥1180 px, tự tô mục đang đọc.
4. **Mục 2 · Luồng chính**: một ví dụ đại diện đi hết hệ thống bằng sequence diagram có `autonumber`, kèm bảng "Trong sơ đồ → Trong mã nguồn → Vai trò".
5. **Từng thành phần**: mỗi thành phần là một `article.comp`: tiêu đề `N.M · Tên`, dòng `src` (file · loại sơ đồ · số bước), "Làm gì", sơ đồ, "Các bước" (`ol.steps`) mỗi bước nói **vì sao**, kể cả sự cố đã từng xảy ra.
6. **Cấu hình / Ghi chú**: bảng thông số dạng `td.num`; `note` / `note crit` cho chỗ tài liệu và mã lệch nhau, lấy mã làm chuẩn.
7. **Footer** nói sơ đồ vẽ bằng gì và cần mạng hay không.

## Hệ màu theo ý nghĩa

Tông kem–cam, có sáng/tối theo hệ điều hành và `data-theme`. Màu luôn mang nghĩa, cùng một nghĩa ở mọi sơ đồ:

| class | Nghĩa |
|---|---|
| `ui` xanh dương | màn hình, người dùng chạm vào, trạng thái khởi đầu |
| `proc` cam | tiến trình, bước xử lý |
| `hot` viền đỏ dày | điểm nóng, chỗ phức tạp/rủi ro |
| `hw` tím | phần cứng |
| `store` xám / `file` xám viền đứt | dữ liệu bền / file cầu nối |
| `dec`, `human` vàng | quyết định / chờ người |
| `ok` xanh lá, `bad` đỏ | kết thúc tốt / hỏng |
| `muted` xám viền đứt | kết thúc thụ động (hết hạn, bỏ qua) |

Script renderer tự chèn `classDef` cho sơ đồ `flow` và cho mọi sơ đồ có dòng `class ...` (kể cả `stateDiagram`), lấy màu từ token CSS nên đổi theme là vẽ lại.

## Quy tắc sơ đồ (user đã sửa trong phiên 09/10/2026)

- **Khối trong sơ đồ phải gọn.** Khi một khối gánh nhiều việc, chỉ để tên trong khối, đánh số ①②…, và đưa chi tiết sang **bảng nổi bên cạnh** (`figure.dg.dg-split` + `aside.dg-side`): bảng dính khi cuộn ở ≥1000 px, xuống dưới sơ đồ ở màn hẹp. Hàng nhóm `tr.grp` mang đúng số và tên của khối.
- **Giữ tên gốc của khối** (tên đã dùng trong mã/tài liệu, ví dụ "Khởi động", "Dựng công thức (4.3)"); không tự đặt tên mới "cho hay hơn".
- **Mũi tên không được xéo quá.** Sắp thứ tự khai báo cạnh để nhánh chính nằm ngang; dùng liên kết ẩn `A ~~~ B` để kéo một nút về ngang hàng. Không kéo dài cạnh (`--->`) nếu làm sơ đồ dài ra mà không thẳng hơn.
- **Sơ đồ trạng thái**: `direction LR`, nhãn chuyển trạng thái 2 dòng `hàm()<br/>giải thích`, tô màu từng trạng thái theo bảng trên, sắp thứ tự cạnh để không cắt nhau.
- Mọi sơ đồ có figcaption bắt đầu bằng "Nguồn:" chỉ hàm/file cụ thể, cộng một câu giải thích thuật ngữ trong hình.
- **Nhãn sơ đồ không ngắt giữa từ hoặc mã.** Sơ đồ trình tự tắt tự động bẻ dòng; nếu nhãn dài, cho khung cuộn ngang hoặc rút gọn nhãn và đưa chi tiết vào bảng cạnh sơ đồ. Chỉ xuống dòng tại chỗ người viết chọn bằng `<br/>`.
- **Một bước gồm nhiều việc phải hiện thành các dòng liệt kê ngắn.** Trong nhãn, dùng `<br/>• ` để tách từng việc; không nối nhiều việc bằng dấu chấm giữa rồi để bộ vẽ tự ngắt dòng.
- **Xử lý nội bộ không có mũi tên tự quay.** Đặt các việc phía trên đúng trục của bên xử lý, giữ một nút số bước trên trục. Mũi tên chỉ dùng khi có thông điệp qua lại giữa các bên. Nút số trong sơ đồ trình tự có vòng tròn và chữ lớn **1,4 lần** kích thước mặc định của Mermaid (bán kính 6 → 8,4 px; chữ 12 → 16,8 px).

## Nội dung: viết như bản tiêu chuẩn (user chốt 11/10/2026)

Document là một **standard manual** tự đứng được: minh bạch, ví dụ chuẩn hóa, người mới đọc hiểu mà không cần ngữ cảnh nội bộ. Không nhắc thông tin lấy từ memory, vault hay lịch sử chat khi giải thích: tên phương án hay giao thức cũ không thuộc thiết kế đã chốt (ví dụ "R5"), "agent research", "tầng 1", "user chốt ngày…", nhãn nội bộ ("B + C", "nguyên tắc vàng"), hay cách nói chỉ hiểu được nhờ cuộc chat. Giải thích bằng lý do kỹ thuật và chuẩn công khai. Đường dẫn code trong repo vẫn được dẫn.

**Chú thích thuật ngữ kiểu Wikipedia (user chốt 11/10/2026).** Mỗi thuật ngữ hoặc tên đặc biệt gắn số chú thích (¹ ² ³) ở lần xuất hiện đầu tiên trong phần chữ. Số là link tới mục "Chú thích" ở cuối trang, và chú thích có link quay lại. Mỗi chú thích ghi tên đầy đủ, một hai câu giải thích dễ hiểu, kèm nguồn chuẩn nếu có (RFC, NIST…). Trong sơ đồ không gắn số; thuật ngữ trong hình giải thích ở figcaption.

## Kiểm trước khi giao

Chụp bằng Chrome headless ở 1400 px và 420 px. Trang cuộn mượt nên chụp theo `#id` ra trắng; thay vào đó chép trang sang scratchpad và chèn CSS ẩn các phần khác (chèn ngay sau `<style>` vì file không có `</head>`). Kiểm: không tràn ngang ngoài khung sơ đồ có cuộn ngang, bảng cạnh sơ đồ xuống dưới ở màn hẹp, mũi tên không cắt nhau, chữ/mã không gãy giữa chừng, các việc nội bộ chỉ có nút số, màu đúng nghĩa.
