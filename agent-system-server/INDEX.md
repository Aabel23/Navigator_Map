# Second brain cá nhân

Thư mục này là nguồn chuẩn cho quy tắc, thiết kế và ký ức dùng chung giữa các phiên agent trên máy này. Có thể mở nó như một Obsidian vault. Không có dịch vụ MCP hoặc đồng bộ cloud đang chạy.

## ⚖ HIẾN PHÁP · đọc trước tiên, quan trọng nhất

**[HIEN_PHAP.md](HIEN_PHAP.md)** là văn bản quan trọng nhất của vault (user chốt 10/10/2026). Mọi file khác dưới đây chỉ là **kho lưu trữ kèm theo**, dùng để tra cứu và không được đi ngược hiến pháp.

Tóm tắt: tầng 1 system design (bàn qua chat → operator đặc tả, chia khối → HTML sơ đồ khối và luồng → user sửa → research song song Sonnet med; coder cũng Sonnet med, planner Opus high → tổng hợp, cải tiến, lặp) → tầng 2 từng khối (research → case study → architect → document → debate → improvement → final decision → execution). Kỷ luật: cấm overengineer, bám logic thiết kế, vấn đề phát sinh thì ghi chú và bàn, không tự sửa code.

---

*Kho lưu trữ kèm theo:*

## Đọc theo nhu cầu

- [RULES.md](RULES.md): quy tắc agent đọc/ghi memory và ranh giới với từng dự án.
- [AGENT_BOOTSTRAP.md](AGENT_BOOTSTRAP.md): hướng dẫn khởi động dùng chung; Codex `~/.codex/AGENTS.md` và Claude Code `~/.claude/CLAUDE.md` cùng trỏ tới tệp này.
- [SYSTEM.md](SYSTEM.md): kiến trúc hiện hành, phần đã có, phần còn cần và cách kiểm.
- [TEMPLATE.md](TEMPLATE.md): mẫu note phiên và mục kiến thức nhỏ.
- [TEST.md](TEST.md): ca thử và tiêu chí đạt qua nhiều phiên.

## Ký ức

- `sessions/`: hồ sơ phiên được tạo khi bạn yêu cầu “chốt session, ghi memory”.
- `facts/`: quyết định, sở thích hoặc cách làm bền có nguồn và phạm vi.
- `proposals/`: điều agent suy ra, chưa được bạn xác nhận.

- `skills/`: cách làm lặp lại được, rút từ việc đã thực thi trong phiên.
- [document-framework/manual/STANDARD.md](document-framework/manual/STANDARD.md): **thiết kế chuẩn** cho mọi document (kiểu FexMix_Munual, user chốt 09/10/2026): template, hệ màu theo nghĩa, quy tắc sơ đồ.
- [document-framework/START_HERE.md](document-framework/START_HERE.md): framework tái dùng để phân tích nguồn, viết tài liệu giải thích hệ thống và dựng HTML/CSS cùng phong cách các document FlexMix. Gồm brief, phương pháp, template, CSS và font offline; áp dụng cho đề tài mới mà không cần mở lại trang mẫu.
- [projects/internproj/README.md](projects/internproj/README.md): bản đồ ba repo Git trong `internproj`; từ đây mở note chi tiết đúng repo.

Các fact `confirmed` hiện ghi cách mở đầu câu trả lời, thiết kế chuẩn FexMix_Munual cho mọi document mới, quy tắc cập nhật bản đồ project khi nguồn đã đổi, và cách đọc note project theo 3 tầng. Không suy ra rằng một thiết kế trong `SYSTEM.md` đã được bạn chốt thành quy tắc cá nhân.

## Mục lục

| Note | Phạm vi | Chủ đề |
|---|---|---|
| [facts/luu-md-session-secondbrain.md](facts/luu-md-session-secondbrain.md) | global · confirmed | "lưu md" nghĩa là chạy `/session-secondbrain`, không phải xuất file .md |
| [facts/reply-yess-bosss.md](facts/reply-yess-bosss.md) | global · confirmed | Mở đầu câu trả lời khi user ra lệnh bằng `yess bosss!!!` |
| [facts/document-standard-flexmix-manual.md](facts/document-standard-flexmix-manual.md) | global · confirmed | Mọi document mới theo chuẩn FexMix_Munual; nhãn sơ đồ không gãy, nội bộ chỉ nút số lớn 1,4 lần |
| [facts/document-shared-assets.md](facts/document-shared-assets.md) | global · confirmed | Khi khởi tạo document, tạo `assets/` chung ở gốc, gồm CSS/JS và font cục bộ để mọi trang dùng offline |
| [facts/document-style-framework.md](facts/document-style-framework.md) | global · superseded | Bản cũ: framework theo document project1_server; đã thay bởi chuẩn FexMix_Munual |
| [facts/project-map-upkeep.md](facts/project-map-upkeep.md) | global · confirmed | Cập nhật bản đồ project khi review/cập nhật xác nhận cấu trúc hoặc vai trò code đổi |
| [projects/internproj/README.md](projects/internproj/README.md) | project:internproj · source-observed | Bản đồ ba repo và cách chọn note đúng dự án |
| [facts/routing-naming-standard.md](facts/routing-naming-standard.md) | project:project1_app · confirmed | Chuẩn đặt tên routing tiếng Anh: biến `OBJECT_TARGET_ACTION`, path `/<app\|machine>/<object>/<target>/<action>`, bảng đổi path cũ→mới |
| [facts/tiered-project-context.md](facts/tiered-project-context.md) | global · confirmed | Note project 3 tầng; tiến trình ở STATUS.md có commit neo; báo cáo agent vào archive vault, không quét lại code |
| [projects/internproj/project1_app.md](projects/internproj/project1_app.md) | project:project1_app · source-observed | Tầng 1: chọn file tầng 2 (STATUS, ARCHITECTURE, TESTING, SECURITY, MIDDLEWARE) hoặc archive báo cáo agent |
| [projects/internproj/project1_server.md](projects/internproj/project1_server.md) | project:project1_server · source-observed | Server mẹ, plan, module, test và điểm vào |
| [projects/internproj/version1.1.md](projects/internproj/version1.1.md) | project:version1.1 · source-observed | Runtime máy pha, GUI, phần cứng, deploy và điểm vào |
| [sessions/2026-10-08-plan-live-checklist.md](sessions/2026-10-08-plan-live-checklist.md) | project:project1_server | Kiểm repo, trang plan live cổng 6767, checklist 3 trạng thái, bảng agent; việc còn mở |
| [sessions/2026-10-09-flexmix-manual-standard.md](sessions/2026-10-09-flexmix-manual-standard.md) | project:internproj | Chỉnh sơ đồ FexMix_Munual (bảng cạnh sơ đồ, tên gốc, restyle state, mũi tên); chốt làm chuẩn |
| [facts/project1-app-protocol-focus.md](facts/project1-app-protocol-focus.md) | project:project1_app · confirmed | Tập trung giao thức/gói tin app↔server↔máy; không làm phía máy khi chưa yêu cầu |
| [facts/test-tool-no-cheating.md](facts/test-tool-no-cheating.md) | project:project1_app · confirmed | Tool test luồng: code thật, oracle độc lập, loop có seed, khôi phục, thống kê, thử sabotage |
| [sessions/2026-10-09-menu-crc-image-cache.md](sessions/2026-10-09-menu-crc-image-cache.md) | project:project1_app | CRC (QR CRC-16, menu_version CRC32), sync menu store_gui, giao thức ảnh món B, tool menu_crc_stress; nhánh chưa commit |
| [sessions/2026-10-10-heartbeat-long-poll.md](sessions/2026-10-10-heartbeat-long-poll.md) | project:project1_app | Machine/user trong DB; heartbeat và long-poll: 3 agent, case study, đề xuất bỏ heartbeat theo pha; tài liệu HTML so sánh; chưa code |
| [sessions/2026-10-11-iot-system-design-tier1.md](sessions/2026-10-11-iot-system-design-tier1.md) | project:project1_app | Tầng 1 hệ IoT v1.1: đăng ký OTP, nhận máy kiểu iCloud, serial CPU, Super Admin/Admin/Staff, 5 agent research, 8 lỗ hổng; phần 2–5: tài khoản, sở hữu theo máy, offline; phần 6: Option 1 phân quyền, server hãng + tự chuyển LAN/BT, nguyên tắc vàng, chống phá B+C, kích hoạt kiểu Matter + mã niêm phong; còn mở |
| [facts/project1-app-v11-iot-design-confirmed.md](facts/project1-app-v11-iot-design-confirmed.md) | project:project1_app · confirmed | Quyết định tầng 1 đã chốt: app thay admin_gui, vai Owner/Manager/Employee, Activation Lock, serial CPU, email, người kích hoạt đầu là Owner, phân quyền theo từng máy bật khi share (MVP), bàn giao QR+BT, Option 1 phân quyền, server hãng + LAN/BT âm thầm, nguyên tắc vàng, B+C, kích hoạt kiểu Matter; pair/share 12/10 (BT share BLE, server ký, vé gắn khóa, khóa máy sinh lần bật đầu, thông số trong config) |
| [sessions/2026-10-11-maintainable-architecture-research.md](sessions/2026-10-11-maintainable-architecture-research.md) | project:project1_app | Research kiến trúc dễ bảo trì (4 lớp), 2 vòng 6 agent, HTML `maintainable-large-systems.html`, đối chiếu project1_app; modular monolith vs EDA chưa chốt |
| [sessions/2026-10-11-multi-agent-orchestration-research.md](sessions/2026-10-11-multi-agent-orchestration-research.md) | global | Research điều phối nhiều agent (4 agent): đọc song song/ghi một luồng, debate ít lợi, luồng tối thiểu 8 bước; archive nguồn; chưa HTML, 4 câu hỏi mở (mục đích, bước debate, framework, nơi đặt doc) |
| [sessions/2026-10-12-pairing-device-sharing-research.md](sessions/2026-10-12-pairing-device-sharing-research.md) | project:project1_app | Research pair máy + share device (3 agent): chốt BT share BLE+6 số, server ký share, vé gắn khóa điện thoại, mã niêm phong QR dài, khóa máy sinh lần bật đầu, thông số vào file config, mã cố định khi bán lại; HTML `pairing-and-device-sharing.html`; 3 lỗi bảo mật code máy chưa sửa; Manager gỡ Employee còn mở |
| [sessions/2026-10-11-app-endpoints-auth-research.md](sessions/2026-10-11-app-endpoints-auth-research.md) | project:project1_app | Đếm endpoint app (routing rỗng → ghi 25 route, relay chung), 6 luồng ~21 tính năng, ~20 câu hỏi mở; research tài khoản/đăng nhập/danh tính 3 agent, HTML `account-login-identity.html`; lỗi BT trả `product_key` |
| [facts/project1-app-auth-identity-confirmed.md](facts/project1-app-auth-identity-confirmed.md) | project:project1_app · confirmed | Đăng nhập email, mật khẩu ≥8 không ràng buộc, đăng ký trung tính, access 1h/refresh 30 ngày, nhập lại mật khẩu cho việc nguy hiểm, mất email = mất tài khoản, LAN/BT mã hoá, khoá Keystore + bản quyền ký hạn 7 ngày |
| [facts/save-research-sources-to-vault.md](facts/save-research-sources-to-vault.md) | global · confirmed | Lưu kết quả research, nguồn, case study vào archive vault để định hướng |
| [sessions/2026-10-11-server-database-research.md](sessions/2026-10-11-server-database-research.md) | project:project1_app | Research database server hãng: 3 agent, ~14 thực thể, HTML `server-database.html` dùng ERD chân chim; doc lệch 3 fact đã chốt (mật khẩu, hạn 7 ngày, chuyển chủ) chưa sửa |
| [sessions/2026-10-13-linux-server-and-diagram-standard.md](sessions/2026-10-13-linux-server-and-diagram-standard.md) | project:project1_app | Hướng dẫn Linux server; sửa 17 doc có sơ đồ trình tự; chuẩn sơ đồ active trong second brain |
| [facts/project1-app-server-database-confirmed.md](facts/project1-app-server-database-confirmed.md) | project:project1_app · confirmed | Server giữ bản sao nhật ký; quyền lưu lịch sử; offline thì từ chối lệnh, chỉ giữ thông điệp quản trị; research ở mức khái niệm |
| [facts/doc-data-diagrams-erd.md](facts/doc-data-diagrams-erd.md) | global · confirmed | Doc về database dùng sơ đồ chuẩn ngành dữ liệu (ERD chân chim, state/sequence UML), không dùng sơ đồ khối FexMix |
| [proposals/cach-lam-viec-cua-user.md](proposals/cach-lam-viec-cua-user.md) | global · proposed | Suy luận về cách bạn làm việc, chờ bạn xác nhận |
| [skills/research-stage.md](skills/research-stage.md) | global | Research stage: "deep research" tự chia nhỏ và cử agent, tổng hợp, HTML research có chú thích; bản chạy ở `~/.claude/skills/research-stage/` |
| [skills/kiem-tra-repo.md](skills/kiem-tra-repo.md) | global | "<path> check": kiểm, chạy test, báo, không tự sửa |
| [skills/plan-live-checklist.md](skills/plan-live-checklist.md) | global | Trang plan live + checklist + quy tắc md |
| [skills/bang-agent-hoat-dong.md](skills/bang-agent-hoat-dong.md) | global | Bảng agent tự báo hoạt động trên trang live |
