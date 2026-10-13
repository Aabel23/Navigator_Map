---
name: kiem-tra-repo
description: Khi user đưa đường dẫn repo kèm "check"/"kiểm" mà không nói gì thêm — kiểm sức khỏe repo, chạy test, báo lỗi và đề xuất sửa, không tự sửa.
source: sessions/2026-10-08-plan-live-checklist.md
status: extracted
---

# Kiểm tra repo ("<path> check")

## Khi dùng
User gửi đường dẫn thư mục + "check". Hiểu là: repo đang ở trạng thái nào, có chạy được không, có gì sai.

## Các bước
1. `ls`, `git status`, `git log --oneline | head`, liệt kê file (bỏ `.git`, venv, node_modules).
2. Đọc `README.md`, `AGENTS.md` / `CLAUDE.md`, file cấu hình mẫu, `.gitignore`.
3. Kiểm file nhạy cảm bị track: `git ls-files | grep -E '\.db$|\.key|\.pem|\.crt|toml$'`. Mở xem trước khi kết luận (ví dụ `.db` rỗng có chủ đích là bình thường).
4. Dựng môi trường **ngoài repo** (scratchpad). Không có pip/venv thì dùng `uv venv` + `uv pip install`. Chạy test với `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider` để không để rác.
5. Test đỏ: tái hiện bằng script nhỏ, tách "lỗi của test" với "lỗi của code" (ví dụ chạy lại server thật trên cổng cố định).
6. Đối chiếu README với thực tế (số test, trạng thái commit, lệnh theo OS).

## Báo cáo
Bảng kết quả → lỗi chính (nguyên nhân + bằng chứng + đề xuất sửa dạng code) → ghi chú khác → hỏi có muốn áp sửa không. **Không sửa khi user chưa đồng ý.** Nói rõ cái gì không chạy được và vì sao (thiếu node, thiếu repo anh em...).
