---
id: navigator-map-ride-hailing-design
type: design
scope: project:navigator_map
status: proposed
source: sessions/2026-10-13-navigator-map-ride-hailing-design.md
valid_from: 2026-10-13
updated: 2026-10-13
supersedes: ""
---

Agent đề xuất, **chưa được user chốt**.

**Kết luận research:** hãng lớn dùng microservice vì quy mô tổ chức, không phải vì điều phối tốt hơn. Lõi quyết định chất lượng: vị trí trong RAM chia ô (S2/geohash; H3 cho phân tích), xếp hạng theo ETA đường bộ, matching theo lô (Hungarian; RL chỉ +0,5–5%), nguồn sự thật nhất quán mạnh + outbox. Chọn theo quy mô: vài nghìn tài xế → modular monolith + Postgres.

**19 khối:** 10 khối cũ + `identity`, `fleet`, `tracking`, `realtime`, `events`, `trip`, `dispatch`, `pricing`, `guidance`. Hai thay đổi khối cũ: `DocumentStore.put_if(version)` (CAS) và routing ETA một-đích-nhiều-nguồn (Dijkstra ngược). GPS tài xế vẫn vào qua `ingest` rồi chia cho `tracking`, `guidance`, `traffic` (tài xế là cảm biến traffic miễn phí cho VN).

**Phản biện mô hình 5 repo + Supabase webhook của user:**
- Webhook (`pg_net`) không retry → cần sweeper quét bảng định kỳ (pg_cron) + handler idempotent.
- Timeout offer phải nằm trong DB (`offers.expires_at`), không trong RAM; auto-deploy làm mất timer.
- Chống nhận trùng bằng DB: unique index `trips(driver_id) where status in (MATCHED, ARRIVING, IN_TRIP)` + `UPDATE ... WHERE status AND version`; `busy` của fleet suy ra từ `trips`.
- Luật "chỉ đọc" phải cưỡng chế: schema + Postgres role riêng mỗi service, đọc qua view; không dùng chung `service_role`.
- Lệch tải: Coder 1 quá tải (dùng Supabase Auth), `ingest` nên tách, Coder 5 phần lớn đã có sẵn.
- Thêm repo `contracts` (OpenAPI + JSON Schema + SQL), mock sinh bằng Prism, contract test, staging, cùng region Singapore.
