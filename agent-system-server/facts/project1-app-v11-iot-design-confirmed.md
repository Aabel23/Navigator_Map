---
id: project1-app-v11-iot-design-confirmed
type: decision
scope: project:project1_app
status: confirmed
source: sessions/2026-10-11-iot-system-design-tier1.md
valid_from: 2026-10-11
updated: 2026-10-11
supersedes: ""
---

Các quyết định tầng 1 user đã chốt cho hệ IoT máy pha v1.1 (máy ↔ server trung gian ↔ app):

- **App thay thế hoàn toàn `admin_gui`.** Phân quyền chặt. Tham khảo mô hình nhóm quyền ở `version1.1/admin_gui/permissions.py` (thư mục này đã bị xoá khỏi `project1_app` ngày 2026-10-11; bản còn ở `internproj/version1.1/`).
- Đăng ký: thông tin, mật khẩu, email, xác nhận OTP qua mail. Ai cũng đăng ký như nhau. **Giữ email** làm danh tính; user đã bác phương án SĐT (2026-10-11).
- Nhân viên **tự đăng ký**, rồi được bàn giao máy. Không dùng kiểu chủ tạo tài khoản hộ hay PIN.
- Vai: **Owner / Manager / Employee** (chốt 2026-10-11, thay cho tên tạm Super Admin / Admin / Staff; khớp owner/manager/staff của `admin_gui`). **Không** có luật mỗi máy một chủ.
- Nhận máy kiểu **iCloud / Activation Lock**: kích hoạt lần đầu tại máy thì máy khoá vào tài khoản, khoá nằm ở server.
- Định danh máy = **serial CPU**.
- Bàn giao máy cho nhân viên bằng QR hoặc Bluetooth, **làm cả hai ngay bản đầu**. Sau đó làm việc hằng ngày không cần QR/BT. Một máy có nhiều nhân viên. Quyền share do chủ chỉnh.
- App được tắt món, sửa menu, khoá máy, nhưng phải gắn với phân quyền.

- **Mô hình sở hữu và phân quyền MVP (chốt 2026-10-11, thay mô hình doanh nghiệp):** ai cũng đăng ký tài khoản như nhau. **Người kích hoạt máy đầu tiên mặc định là Owner của máy đó.** Chưa share thì owner dùng toàn quyền, app không hiện phân quyền. **Share máy lần đầu thì mới bật tính năng phân quyền** (Manager/Employee; vai cố định theo Option 1, không chỉnh quyền từng người).
- **Người được share mặc định là Employee** của máy đó (chốt 2026-10-11). Người được share hoặc phân vai **không cần đồng ý hay thao tác gì**: phân là có hiệu lực ngay.
- **Đổi vai (phương án b, chốt 2026-10-11):** Owner nâng được Employee lên tối đa Manager. Manager chỉ được share thêm Employee, không nâng vai ai.
- **Mỗi máy đúng 1 Owner ở MVP, có chuyển quyền sở hữu ngay bản đầu (chốt 2026-10-11):** Owner cũ giao máy cho người khác rồi tự xuống Manager. Câu "không có luật mỗi máy một chủ" ở trên được thay bằng điều này cho MVP.
- **Phạm vi theo từng máy (phương án A):** mỗi máy có danh sách người và vai riêng. Chủ nhiều máy share từng máy. Không có doanh nghiệp, không gian chung hay nhóm máy ở bản MVP.
- **Bỏ thu thập thông tin doanh nghiệp khỏi bản đầu.**
- **Dữ liệu món và nguyên liệu nằm local trên máy (chốt 2026-10-11).** Lý do user nêu: thiết bị IoT đã làm như vậy từ lâu, mất mạng không được làm hỏng vận hành.
- **Mất mạng vẫn phải quản trị được:** không có wifi/Internet thì app nói chuyện trực tiếp với máy qua **Bluetooth** (user đề xuất, chốt 2026-10-11). Bác phương án "MVP chấp nhận mất mạng thì không quản trị". **Bluetooth là tùy chọn**, chỉ dùng khi không có mạng; không bắt nhân viên kết nối Bluetooth cho việc thường ngày. *Được làm rõ sau cùng ngày:* mất Internet thì đi LAN trước, mất cả wifi mới đến BT; offline chỉ làm việc vận hành (xem đơn, kho, nạp kho, tắt/bật món, đổi wifi), xem mục "Nguyên tắc vàng" và "B + C".
- **Server là gateway giữa máy và app, không chứa dữ liệu** (chốt 2026-10-11). Server **chỉ giữ đăng nhập (tài khoản) và danh sách máy**; mọi dữ liệu khác nằm trên máy và chỉ đi qua server.
- **Phân quyền và offline: Option 1 "kiểu khoá thông minh" (chốt cuối 2026-10-11, user quay lại sau khi thử "phụ thuộc online" vì Option 1 an toàn hơn):** server giữ bảng user và bảng máy (mỗi dòng một người trên một máy) và là bản chuẩn; máy giữ bản sao danh sách quyền có hạn dùng; mất kết nối server thì mọi người vẫn làm việc theo quyền đang có nhưng không đổi được quyền. Vai cố định, không chỉnh quyền từng người. Phương án "phụ thuộc online, máy không giữ bản sao" đã bị thay. Còn mở: (a) gỡ người tại chỗ qua BT (agent đề xuất; nay vướng nguyên tắc vàng "offline không gỡ người", cần user quyết), (b) hỏi lại mật khẩu cho việc nguy hiểm, độ dài hạn dùng; đề xuất vé ký (Option 4) làm lớp xác minh BT/danh tính máy. Research: archive/permission-offline-research-2026-10-11.md.
- **Chống nhân viên phá trước khi nghỉ (chốt 2026-10-11): B + C.** B: offline chỉ cho việc vận hành; việc nguy hiểm (sửa menu, giá, xoá nguyên liệu, khoá máy) bắt buộc online. C: nhật ký theo người, không xoá được, báo chủ việc bất thường. Ngoài ra dựa vào vai cố định và pháp luật. ~~Còn mở: nhật ký nằm ở đâu~~ → đã chốt 11/10/2026: server giữ bản sao, bản gốc trên máy ([project1-app-server-database-confirmed](project1-app-server-database-confirmed.md)). Chi tiết: projects/internproj/project1_app/OFFLINE_THREATS.md.
- **Server của hãng (cloud) + tự chuyển chế độ (chốt 2026-10-11, phương án D):** bình thường app → server hãng → máy. Mất Internet thì app và máy tự nói chuyện trực tiếp trong wifi quán (chế độ LAN); mất cả wifi thì qua Bluetooth. Chuyển **âm thầm, tự động, không hiện dấu hiệu chế độ** trên app. Máy không bao giờ làm server; ở LAN/BT máy chỉ kiểm quyền bằng bản sao. Thay cho ý "server đặt tại quán".
- **Nguyên tắc vàng (chốt 2026-10-11):** chế độ LAN và Bluetooth không bao giờ mạnh hơn online; ba chế độ chung cách xác minh danh tính và mức mã hoá. Offline không share, gỡ người, đổi vai, chuyển chủ, đăng ký mới; việc nguy hiểm (sửa menu, giá, xoá nguyên liệu, khoá máy) cũng không (B). **Tắt/bật món coi là việc vận hành, làm được offline** (agent đề xuất, user trả lời "ok"; xác nhận lại nếu nghi ngờ).
- **Kích hoạt lần đầu: mã niêm phong theo hộp máy (phương án B, chốt 2026-10-11):** mỗi máy kèm một mã bí mật niêm phong trong hộp hoặc giấy bảo hành; kích hoạt phải có mã này. Hợp với bán qua đại lý (mã đi theo hộp). Kích hoạt lần đầu bắt buộc online (theo nguyên tắc vàng). **Cách làm: kiểu Matter (phương án A, chốt 2026-10-11):** quét mã niêm phong → mã làm chìa mở kênh Bluetooth mã hoá → máy trình giấy khai sinh của hãng → app gửi wifi qua kênh đó → máy lên server → người quét thành Owner. Bỏ bước máy hiện QR trên màn hình. **Mã niêm phong cố định suốt đời máy, bí mật, chỉ có tác dụng khi máy ở trạng thái "chưa có chủ"; không dùng làm tên hiển thị, định danh vẫn là serial CPU** (chốt 2026-10-11, thay ý "dùng một lần" chốt trước đó cùng ngày). **Đổi wifi về sau: Owner hoặc Manager đứng cạnh máy gửi wifi mới qua Bluetooth từ app; coi là việc vận hành, làm được khi offline** (chốt 2026-10-11). Bán lại: chủ cũ gỡ máy → máy về "chưa có chủ" → người mua dùng lại mã niêm phong. Còn mở: đường dự phòng hãng xử lý tranh chấp (hoá đơn + thời gian chờ), và chuyển chủ có cho chủ cũ rời hẳn không.
- **Pair và share (chốt 2026-10-12, nguồn: sessions/2026-10-12-pairing-device-sharing-research.md):**
  - Share qua Bluetooth **vẫn có ở MVP** (giữ quyết định cũ, bác khuyến nghị bỏ), làm bằng **BLE, hai điện thoại hiện mã 6 số để so**.
  - **Server ký giấy phép share**; người share chỉ xác nhận (vân tay/PIN), điện thoại không giữ khóa ký.
  - **Vé dùng cho LAN/BT gắn khóa riêng của điện thoại** ngay từ MVP (máy bắt app ký thử thách).
  - **Mã niêm phong là chuỗi ngẫu nhiên dài in QR** (~100 bit); không PIN ngắn, không PAKE.
  - **Máy tự sinh cặp khóa ở lần bật đầu, gắn với mã niêm phong**; chưa đòi xưởng nạp khóa/chứng chỉ ở MVP.
  - **Các thông số thời hạn/ngưỡng là biến cấu hình lâu dài, gom vào một file config, dev chỉnh được** (hạn vé, hạn bản sao quyền, hạn mã mời, khung chờ claim…). Giá trị mặc định chưa chốt.
  - **Mã niêm phong giữ cố định suốt đời máy khi bán lại**; chấp nhận rủi ro chủ cũ biết mã.
- *Đã bị thay (không còn hiệu lực):* "tạo doanh nghiệp là tùy chọn", "doanh nghiệp ngầm", "máy thuộc doanh nghiệp", "nhập thông tin doanh nghiệp lúc tạo".

- Tài khoản, đăng nhập, danh tính điện thoại và kênh mã hoá app↔máy: xem [project1-app-auth-identity-confirmed](project1-app-auth-identity-confirmed.md) (chốt 11/10/2026).

Những điểm còn chờ chốt nằm trong session note. Đây là tầng 1: chưa chọn công nghệ.
