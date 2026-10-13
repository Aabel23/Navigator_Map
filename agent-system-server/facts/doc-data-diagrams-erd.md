---
id: doc-data-diagrams-erd
type: preference
scope: global
status: confirmed
source: sessions/2026-10-11-server-database-research.md
valid_from: 2026-10-11
updated: 2026-10-11
supersedes: ""
---

Doc về database / mô hình dữ liệu phải dùng **sơ đồ chuẩn của ngành dữ liệu**, không dùng kiểu sơ đồ khối/luồng của chuẩn FexMix cho phần dữ liệu (user 11/10/2026: "phải dùng sơ đồ data của ngành khoa học dữ liệu, nếu dùng doc của ta sẽ khá khó nhìn").

Cách áp dụng (agent làm, user chưa phản đối): ERD ký hiệu chân chim — mức khái niệm (chỉ thực thể + quan hệ) cho bức tranh toàn cục, mức logic (cột, kiểu, PK/FK/UK) cho từng nhóm; vòng đời dùng state UML, luồng dùng sequence. Vẫn giữ khung trang, màu và chú thích của [document-standard-flexmix-manual](document-standard-flexmix-manual.md). Ghi chú kỹ thuật: ERD cần Mermaid ≥ 11.6.0 nếu dùng `direction`; tránh nhãn cạnh bắt đầu bằng `>`.
