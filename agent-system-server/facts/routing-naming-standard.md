---
id: routing-naming-standard
type: naming-convention
scope: project:project1_app
status: confirmed
source: current-conversation, user request on 2026-10-09 ("đặt lại tên toàn bộ routing thành tiếng anh, có cấu trúc, lưu chuẩn vào vault"); áp dụng trong project1_app/MODULE_PATTERN.md
valid_from: 2026-10-09
updated: 2026-10-09
supersedes: ""
---

# Chuẩn đặt tên routing (project1_app)

User yêu cầu toàn bộ routing dùng tiếng Anh và có cấu trúc. Cấu trúc cụ thể dưới đây do agent đề xuất và áp dụng cùng yêu cầu đó; nguồn hiện hành là `project1_app/MODULE_PATTERN.md` mục "Tên biến và đường dẫn routing".

## Quy tắc

| Phần | Dạng | Ví dụ |
|---|---|---|
| Biến Python | `<ĐỐI_TƯỢNG>_<MỤC_TIÊU>_<HÀNH_ĐỘNG>` UPPER_SNAKE_CASE | `MACHINE_MENU_UPDATE` |
| Biến Dart | cùng thứ tự, lowerCamelCase | `machineMenuUpdate` |
| Path app gọi | `/app/<đối_tượng>/<mục_tiêu>/<hành_động>` | `/app/machine/menu/update` |
| Path máy gọi | `/machine/<mục_tiêu>/<hành_động>` (đối tượng là chính máy, bỏ) | `/machine/command/poll` |

- Đoạn đầu là **bên gọi** (`app` dùng token, `machine` dùng `product_key`), chọn theo ai gọi: trạng thái máy do app hỏi → `/app/machine/status/get`.
- Đối tượng: `user` | `machine`. `user/machine/*` = tập máy của tài khoản (register/list/remove); `machine/*` = thao tác trên một máy.
- Mục tiêu: danh từ số ít (`account`, `otp`, `session`, `share`, `staff`, `name`, `status`, `menu`, `ingredient`, `heartbeat`, `command`, `result`).
- Hành động: động từ cuối (`get`, `list`, `create`, `update`, `remove`, `register`, `send`, `verify`, `accept`, `revoke`, `refill`, `poll`, `login`, `logout`); không bắt buộc trùng HTTP method.
- Path chữ thường a-z, nhiều từ trong một đoạn nối `-`, không dấu, không `/` cuối, tham số ở body/query.
- Kiểm nhanh: bỏ đoạn bên gọi, đổi `/` → `_` phải ra tên biến (path máy thêm tiền tố `MACHINE_`).
- Ba file phải khớp: `server/config/routing.py`, `app/flutter_app/lib/config/routing.dart`, `version1.1/machine/config/routing.py`; đổi path thì sửa cả ba + test cùng lúc. *(Nguồn hiện hành 12/10/2026: file server là `server/configuration/routing.py`; `routing.dart` chưa có vì app chưa có lớp kết nối.)*
- Ngoài phạm vi routing: tên lệnh gửi máy (`instruction`, vd `cap_nhat_menu`) và trường gói tin (`thay_doi`, `ket_qua`, `lenh`) vẫn tiếng Việt; đổi chúng là thay hợp đồng gói tin riêng.

## Bảng đổi ngày 2026-10-09 (path cũ → mới)

| Cũ | Mới |
|---|---|
| `/app/dang-ky-nguoi-dung`, `/app/gui-ma-otp`, `/app/xac-minh-otp` | `/app/user/account/register`, `/app/user/otp/send`, `/app/user/otp/verify` |
| `/app/dang-nhap`, `/app/xac-minh-dang-nhap`, `/app/dang-xuat` | `/app/user/session/login`, `/app/user/session/verify`, `/app/user/session/logout` |
| `/app/dang-ky-may`, `/app/may-cua-toi`, `/app/go-may` | `/app/user/machine/register`, `/app/user/machine/list`, `/app/user/machine/remove` |
| `/app/tao-ma-chia-se`, `/app/nhan-chia-se` | `/app/machine/share/create`, `/app/machine/share/accept` |
| `/app/nhan-vien-may`, `/app/thu-hoi-quyen` | `/app/machine/staff/list`, `/app/machine/staff/revoke` |
| `/app/doi-ten-may`, `GET /machine/trang-thai` | `/app/machine/name/update`, `GET /app/machine/status/get` |
| `/app/nhan-menu`, `/app/cap-nhat-menu` | `/app/machine/menu/get`, `/app/machine/menu/update` |
| `/app/nhan-kho`, `/app/nap-kho` | `/app/machine/ingredient/get`, `/app/machine/ingredient/refill` |
| `/machine/heartbeat`, `/machine/hoi-lenh`, `/machine/tra-ket-qua` | `/machine/heartbeat/send`, `/machine/command/poll`, `/machine/result/send` |

Dart `userLoginVerify` đổi thành `userSessionVerify`; server vẫn chưa có route này (lệch login cũ, xem [STATUS](../projects/internproj/project1_app/STATUS.md)).

Chỉ áp trong repo `project1_app` (gồm `version1.1/machine/` bên trong). Không động tới `project1_server` và repo `internproj/version1.1` riêng; nếu chúng gọi các route này thì phải đổi theo trước khi chạy chung.
