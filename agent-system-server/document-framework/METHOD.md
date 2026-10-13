# Cách suy nghĩ và thiết kế một document kiểu này

## 1. Khóa mục đích trước khi chọn layout

Viết một câu: “Tài liệu này giúp **ai** quyết định/hiểu/làm **việc gì** dựa trên **bằng chứng nào**.” Nếu không nói được, chưa nên vẽ. Kiểm người đọc đã biết gì; bỏ giải thích thừa. Chọn một kết luận hoặc mô hình chính để mở bài.

## 2. Xây mô hình từ nguồn, không từ template

Đọc code/config/dữ liệu/quyết định thật; ghi hiện trạng và đề xuất riêng. Lập bảng thực thể, trách nhiệm, đầu vào, đầu ra, ranh giới và người sở hữu. Theo một tình huống cụ thể từ tác nhân tới kết quả. Với hệ thống kỹ thuật, soi thêm xác thực, ghi bền, lỗi, retry, khôi phục, triển khai và người vận hành. Với chủ đề khác, thay bằng các rủi ro tương đương; không ép từ vựng kỹ thuật vào nó.

Giữ một sổ khẳng định như [BRIEF.md](BRIEF.md). Điều không có nguồn thì ghi `chưa rõ`, `giả định` hoặc bỏ. Không biến sơ đồ đẹp thành sự xác nhận ngầm rằng thiết kế đã được duyệt.

## 3. Chọn lớp đọc và thứ tự

| Lớp | Câu hỏi người đọc | Dạng tốt nhất |
|---|---|---|
| Mở đầu | Đây là gì, quyết định chính là gì, mức chắc chắn ra sao? | Tiêu đề có thông tin, lead 2–4 câu, metadata ngắn |
| Tổng quan | Những phần nào liên hệ với nhau? | Một sơ đồ có ranh giới và chú giải; hoặc bảng nếu ít phần |
| Tình huống | Một việc thật đi qua hệ thống thế nào? | Sơ đồ tuần tự/flow có số bước + bảng giải thích |
| Cơ chế | Mỗi phần làm gì, nhận/trả gì, trạng thái nào? | Thẻ thành phần, bảng hợp đồng, sơ đồ cục bộ |
| Thực thi | Làm theo thứ tự nào, đạt bằng gì? | Bảng bước–việc–kiểm, phụ thuộc, owner, trạng thái |
| Giới hạn | Cái gì chưa chốt/chưa kiểm; bước nào bị chặn? | Callout ngắn, câu hỏi có chủ sở hữu và hệ quả |

Không dùng đủ sáu lớp theo thói quen. Với bài ngắn, kết hợp hoặc bỏ lớp không cần. Với bài dài, giữ các lớp nhưng nhóm theo câu hỏi của người đọc, không theo thứ tự file nguồn.

## 4. Quy tắc chọn hình

- **Bản đồ hệ thống** khi người đọc cần hiểu ranh giới, sở hữu, luồng chính. Đặt trước chi tiết. Mũi tên ghi rõ cái gì đi qua, hướng nào. Màu theo vai trò cố định; nét đứt cho dự kiến/không đồng bộ.
- **Sơ đồ tuần tự** khi thứ tự gọi, commit, retry, ack quan trọng. Giữ chữ trong hình ngắn; dùng bảng đánh số ngay dưới để nói endpoint, dữ liệu, điều kiện và lỗi.
- **Flow/decision** khi người đọc cần hiểu nhánh chọn hoặc nhánh từ chối. Viết nhãn “có/không”, điều kiện rõ; vẽ đường lỗi tới kết quả.
- **Bảng** khi cần so sánh nhiều đối tượng theo cùng thuộc tính hoặc theo dõi bước và phép kiểm. Không dùng bảng để thay thế một đoạn văn ngắn.
- **Ví dụ nhỏ** sau sơ đồ trừu tượng: đầu vào, biến đổi, đầu ra và điều xảy ra nếu sửa một yếu tố. Số liệu ví dụ phải ghi là ví dụ; số liệu thật phải có nguồn.

Mỗi hình có tiêu đề nêu điều nó giải thích, `aria-label`/`alt`, chú giải, `figcaption` nêu cách đọc và giới hạn. Nếu hình rộng, bọc trong vùng cuộn ngang; kiểm trên điện thoại. Hình không thay thế nguồn hay phần giải thích bằng chữ.

## 5. Quy tắc chữ và trạng thái

Tiêu đề nói điều cụ thể (“Đổi giá đi từ trình duyệt tới máy qua ba lần ghi”) thay cho nhãn chung (“Kiến trúc”). Một đoạn một ý. Thuật ngữ xuất hiện lần đầu cần định nghĩa ngắn, rồi dùng nhất quán. Viết rõ **ai làm gì, ở đâu, lúc nào, điều kiện nào, kết quả nào**. Với bước triển khai, mỗi dòng có một phép kiểm quan sát được.

Nhãn trạng thái dùng theo nghĩa, không theo màu đơn thuần: `đã có/đã kiểm`, `đang làm`, `đề xuất`, `chờ quyết định`, `chưa kiểm`, `không chọn`. Metadata đầu trang cho biết phiên bản, nguồn, ngày, trạng thái; từng khu vực có thể có trạng thái riêng. Khi nguồn và bản trình bày tách nhau, chọn một nguồn chuẩn (thường Markdown/data), sinh HTML từ đó và kiểm không trôi.

## 6. Hệ hình thức

Nền giấy ấm, chữ than, màu đất nung cho điểm nhấn. Serif cho đọc dài/tiêu đề; sans cho nhãn, menu và bảng; mono cho code/id. Chiều rộng trang khoảng 1240–1440 px, cột mục lục 220–230 px trên màn lớn, đoạn văn giới hạn khoảng 74–78 ký tự. Bề mặt và đường viền nhẹ tạo tầng, không dùng màu để trang trí. Màu xanh cho UI, đất nung cho xử lý, tím cho thiết bị, xám cho dữ liệu bền, vàng cho chờ/chú ý, xanh lá cho đạt, đỏ cho lỗi. Dùng `document.css`; đổi token nếu tài liệu mới có nhận diện riêng.

## 7. Kiểm trước khi giao

1. Đọc nhanh từ đầu: người đọc có hiểu kết luận và hành động sau 30 giây không?
2. Đối chiếu từng claim quan trọng với nguồn; nhãn `đã có/đã chốt` có đúng thời điểm không?
3. Đi một luồng cụ thể từ đầu tới cuối; kiểm tên, hướng mũi tên, đầu vào/ra, ranh giới, nhánh lỗi.
4. Kiểm mục lục/anchor, bảng, sơ đồ, chú giải, caption, link nguồn và đường dẫn asset.
5. Render desktop, tablet, mobile, dark và print; không tràn trang ngoài vùng sơ đồ/bảng được cuộn; chữ Việt rõ; tab/focus dùng được.
6. Nếu HTML sinh từ Markdown, sửa nguồn rồi sinh lại và kiểm diff; không sửa bản sinh tay.

**Dừng đúng mức:** không thêm hero, card, FAQ, timeline, ma trận hay sơ đồ chỉ vì framework có sẵn. Mỗi thành phần phải trả lời một câu hỏi thật của người đọc.
