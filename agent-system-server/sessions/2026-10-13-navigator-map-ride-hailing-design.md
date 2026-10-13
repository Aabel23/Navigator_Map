---
id: session-20261013-navigator-map-ride-hailing-design
type: session-learning
scope: project:navigator_map
status: extracted
date: 2026-10-13
source: current-conversation (Claude Code cloud, nhánh claude/vigilant-dirac-vlvzod)
---

# Mục tiêu và chuẩn đạt
Bạn muốn biết app gọi xe kiểu Grab thiết kế hệ thống thế nào, có thiết kế nào tốt hơn, rồi áp vào Navigator_Map: từ server chỉ đường hiện tại mở rộng thành nền tảng gọi xe, chia sao cho 5 người code song song bằng AI không dẫm chân nhau.

## Những lần chỉnh hướng
- Agent khuyên modular monolith → bạn hỏi "sau này scale làm sao tách" → agent trả lời bằng cách tách theo strangler fig, giữ Protocol, mỗi module sở hữu dữ liệu riêng.
- Agent thiết kế 19 khối lắp trong `composition.py` → bạn đổi hướng: phá `composition.py`, gom thành **5 macro-service / 5 repo**, dùng **Supabase + Database Webhooks** thay Kafka/outbox, API-first + mock + auto-deploy PaaS. Lần sau: khi bàn chia việc cho nhóm, tính tới số người và cách AI giữ ngữ cảnh hẹp, không chỉ tính kỹ thuật.

## Quyết định và giới hạn
- [user-proposed] Chia 5 lãnh địa: (1) Gác cổng: `api`, `identity`, `realtime`; (2) Thủ kho: `trip`, `pricing`, giữ CAS; (3) Bà mối: `dispatch`, `fleet`, timeout 15 s; (4) Mắt thần: `ingest`, `tracking`, `guidance`; (5) Bản đồ học: `routing`, `mapdata`, `traffic`, `roadstate` + reverse Dijkstra. Một project Supabase chung, ai sở hữu bảng thì người khác chỉ đọc. Bạn hỏi "đủ chiến chưa", **chưa chốt**.
- [source-observed] `server/ARCHITECTURE_LOCK.md` (khoá 2026-09-13): 10 khối, nối bằng `typing.Protocol`, lắp duy nhất ở `server/api/composition.py`, luật phụ thuộc kiểm bằng `server/tests/test_dependency_rules.py`; rule 11 cấm thêm hạ tầng khi chưa có yêu cầu; rule 17 chỉ nguồn dữ liệu miễn phí; §7: chưa có auth, map matching, reroute, Postgres adapter.
- [agent-inferred] Phản biện mô hình 5 repo: xem [proposals/navigator-map-ride-hailing-design.md](../proposals/navigator-map-ride-hailing-design.md).

## Sản phẩm hiện hành
- Báo cáo deep research (tiếng Việt): `Navigator_Map/reports/Thiết kế hệ thống gọi xe.md`; ghi chú nguồn: `Navigator_Map/research_notes/Thiết kế hệ thống gọi xe/` (4 file: architecture_styles, geo_location, matching_dispatch, consistency_and_small_scale). Nguồn chỉ đọc qua tóm tắt search vì proxy chặn fetch; số liệu yếu đã gắn nhãn.
- Commit `90422dc` trên nhánh `claude/vigilant-dirac-vlvzod`. Chưa sửa code server.

## Phần còn mở
- Chốt mô hình 5 repo hay monorepo 5 thư mục (CLAUDE.md + CODEOWNERS + Tach/import-linter).
- Chốt cách vá 4 lỗ hổng: sweeper cho webhook mất, timer bền trong DB, unique index + CAS chống nhận trùng, schema + role riêng thay `service_role` chung.
- Chốt chia lại tải: Supabase Auth thay `identity`; tách `ingest` (GPS → Coder 4, feed ngoài → Coder 5); `pricing` về Coder 5?; PostGIS trước Redis.
- Supabase là dịch vụ freemium: xem có trái luật "chỉ miễn phí" của dự án không (rule 17 nói về nguồn dữ liệu).
- Việc kế tiếp agent đã đề xuất: dựng repo `contracts` (OpenAPI, JSON Schema webhook, SQL schema/role/view/unique index, state machine `trip`).
