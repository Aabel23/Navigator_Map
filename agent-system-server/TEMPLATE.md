# Mẫu note memory

Một note chỉ chứa thông tin cần dùng lại. Tên file có ID ổn định; Obsidian đọc YAML Properties và Markdown.

## Hồ sơ phiên: `sessions/YYYY-MM-DD-chu-de.md`

```markdown
---
id: session-YYYYMMDD-chu-de
type: session-learning
scope: project:ten-du-an
status: extracted
date: YYYY-MM-DD
source: current-conversation
---

# Mục tiêu và chuẩn đạt
Bạn muốn sản phẩm giải quyết gì; nhìn thế nào là đạt.

## Những lần chỉnh hướng
- Hiểu sai trước đó → bạn sửa thế nào → lần sau làm gì khác.

## Quyết định và giới hạn
- [user-confirmed] Điều bạn nói rõ hoặc chốt.
- [source-observed] Điều đối chiếu từ file/code, kèm đường dẫn.

## Sản phẩm hiện hành
- Đường dẫn, kết quả kiểm và bản nào đã bị thay.

## Phần còn mở
- Quyết định hoặc phép kiểm chưa xong.
```

`extracted` nghĩa là agent đã rút hồ sơ từ phiên; không có nghĩa bạn duyệt mọi câu trong note.

## Mục bền: `facts/<id>.md` hoặc `proposals/<id>.md`

```markdown
---
id: work-example
type: preference
scope: global
status: confirmed
source: sessions/YYYY-MM-DD-chu-de.md
valid_from: YYYY-MM-DD
updated: YYYY-MM-DD
supersedes: ""
---

Một ý ngắn, có thể áp dụng hoặc kiểm được. Ghi rõ điều kiện áp dụng nếu có.
```

Chỉ dùng `status: confirmed` khi chính bạn nói/chốt nội dung. Suy luận của agent dùng `status: proposed` và đặt trong `proposals/`. `scope` có thể là `global` hoặc `project:<id>`. Khi đổi ý, tạo/sửa mục mới và đánh dấu mục cũ `superseded` với link hai chiều. Không đưa bí mật vào note.
