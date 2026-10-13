# Framework tài liệu giải thích hệ thống

**Phạm vi:** hướng dẫn tái dùng cho tài liệu HTML tiếng Việt về bất kỳ chủ đề nào cần giải thích một hệ thống, quy trình, thiết kế, quyết định hoặc kế hoạch. Đây là **framework do agent rút ra** từ các trang FlexMix ngày 08/10/2026, không phải lời user duyệt mọi quy tắc. Yêu cầu hiện tại và nguồn của chủ đề mới luôn ưu tiên.

> **Thiết kế chuẩn từ 09/10/2026:** [manual/STANDARD.md](manual/STANDARD.md) + [manual/template.html](manual/template.html), trích từ `FexMix_Munual.html` (user chốt). Dùng template đó cho HTML; các bước brief → nguồn → dàn ý → kiểm bên dưới vẫn áp dụng. `template.html`/`document.css` ở thư mục này là bản cũ không có sơ đồ Mermaid, chỉ dùng khi cần trang offline không JavaScript.

## Dùng nhanh

1. Điền [BRIEF.md](BRIEF.md) cho đề tài mới; đọc nguồn thật của đề tài đó. Không cần mở lại các trang FlexMix.
2. Dùng [METHOD.md](METHOD.md) để chọn câu hỏi cần trả lời, sơ đồ và mức chi tiết. Lập dàn ý bằng Markdown trước khi viết HTML.
3. Khi khởi tạo bộ document, tạo `assets/` tại gốc bộ tài liệu và đặt CSS, JavaScript, `fonts.css`, `fonts/` dùng chung ở đó. Tạo trang từ `manual/template.html`, thay nội dung ví dụ và liên kết asset bằng đường dẫn tương đối; không sao chép font riêng cho mỗi trang. Xem [quy tắc asset dùng chung](../facts/document-shared-assets.md).
4. Mở trang ở 1440 px, 768 px và 390 px; kiểm liên kết, tràn ngang, chú giải và bản in. Đối chiếu từng khẳng định quan trọng với nguồn.

Template mở offline bằng trình duyệt; không cần build, CDN hoặc JavaScript. Có theme sáng/tối theo hệ điều hành, mục lục bên trái trên desktop, bảng và sơ đồ cuộn ngang trên màn hẹp, stylesheet in.

## Những thứ phải giữ, những thứ được đổi

**Giữ:** câu mở đầu nói đúng việc tài liệu giúp người đọc làm; bức tranh toàn cục; một ví dụ/luồng đại diện; lớp chi tiết theo nhu cầu; trạng thái `đã có` / `đề xuất` / `chưa kiểm` rõ ràng; nguồn và điều kiện kiểm. Sơ đồ luôn có nhãn, chú giải, chú thích và bản diễn giải bằng chữ.

**Đổi theo đề tài:** thứ tự mục, số sơ đồ, độ dài, nhãn màu theo vai trò, các bảng, tên component. Một ghi chú ngắn không cần cố đủ mọi mục; một tài liệu kỹ thuật dài cần nhiều lớp đọc.

**Không mang theo:** sự kiện, số liệu, kiến trúc, endpoint, thuật toán hoặc quyết định riêng của FlexMix. Bảng màu chỉ là nhận diện thị giác lấy từ các trang mẫu, không phải bằng chứng cho nội dung.

## Vì sao các trang mẫu hiệu quả

- [Thiết kế server](/home/abel/project/internproj/project1_server/docs/server_architect.html) đặt sơ đồ toàn hệ thống trước, rồi đi theo một thao tác đổi giá, sau đó mới giải thích từng luồng và lớp bảo mật.
- [Plan](/home/abel/project/internproj/project1_server/docs/server_plan.html) biến thiết kế thành khối, đầu vào/đầu ra, bước, phép kiểm và câu hỏi chờ chốt. Trang được dựng từ Markdown để trạng thái không trôi khỏi nguồn.
- [Cẩm nang mật mã](/home/abel/project/internproj/project1_server/docs/cryptography/crypto-primer.html) đi từ “nằm ở đâu” đến “hoạt động thế nào” và một ví dụ byte cụ thể; tách hiện trạng khỏi đề xuất.
- [Sơ đồ bảo vệ gói](/home/abel/project/internproj/project1_server/docs/cryptography/packet-security.html) dùng sơ đồ cho đường đi, nhánh lỗi và trạng thái; chữ bên cạnh trả lời mục đích, đầu vào, đầu ra, giới hạn.

Mẫu chung không phải một dàn mục cố định. Đó là **thứ tự hiểu**: kết luận và phạm vi → bản đồ → tình huống cụ thể → cơ chế → phần việc/kiểm chứng → giới hạn/quyết định. Giao diện hỗ trợ thứ tự đó bằng phân cấp chữ, màu theo ý nghĩa, sơ đồ có caption và khoảng trắng đủ đọc.

## Bộ file

| File | Vai trò |
|---|---|
| `BRIEF.md` | Các câu hỏi đầu vào trước khi viết |
| `METHOD.md` | Quy trình phân tích, chọn hình, viết và kiểm |
| `template.html` | Trang mẫu HTML có đủ component để sao chép/bỏ bớt |
| `document.css` | Token và component dùng chung, sáng/tối/in/mobile |
| `fonts.css`, `fonts/` | Font offline chép từ bộ tài liệu FlexMix: Be Vietnam Pro, Source Serif 4, JetBrains Mono. File gốc ghi OFL; khi phân phối ra ngoài, kiểm và kèm license tương ứng. |

## Nguồn gốc và giới hạn

Đây là bản trích xuất từ bốn trang ở trên, không phải bản sao nguyên CSS hơn 2.000 dòng của một dự án. Nó tái tạo hệ màu, kiểu chữ, nhịp trang và những component có thể tái dùng. Sơ đồ nội dung vẫn phải được thiết kế riêng; một framework không thể tự tạo sự thật hoặc phép kiểm cho đề tài chưa có nguồn.
