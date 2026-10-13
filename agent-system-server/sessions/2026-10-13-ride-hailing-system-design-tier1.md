---
id: session-20261013-ride-hailing-system-design-tier1
type: session-learning
scope: project:navigator_map
status: extracted
date: 2026-10-13
source: current-conversation (phiên cloud, repo Navigator_Map, nhánh claude/determined-bell-jrp6o7)
---

# Mục tiêu và chuẩn đạt

- [user-confirmed] Đã có map render engine cơ bản (`client/map`). Muốn research thiết kế các hệ thống lớn.
- [user-confirmed] Muốn bàn system design của một hệ thống **chỉ đường + bản đồ + phân phối tài xế**, build app kiểu **Grab / Xanh SM**.
- Đang ở **tầng 1, bước 1** của `HIEN_PHAP.md` (bàn qua chat). User **chưa chốt** phương án; chưa viết HTML, chưa research song song, chưa code.

## Những lần chỉnh hướng

- Lượt 1, agent research "hệ thống bản đồ lớn" chung chung → user thu hẹp: hệ thống gọi xe đầy đủ (map + chỉ đường + điều phối tài xế), kiểu Grab / Xanh SM.

## Research vòng 1: case study (mức kiểm: đã tìm = có nguồn web; nhớ = hiểu biết sẵn có, chưa kiểm)

| Công ty | Ý thiết kế | Mức kiểm | Nguồn |
|---|---|---|---|
| Google Maps | Dự đoán giao thông 10–50 phút tới cho từng đoạn, xếp hạng tuyến ứng viên theo ETA dự đoán; tầng dự đoán tách khỏi tầng tìm tuyến | đã tìm | https://deepmind.google/blog/traffic-prediction-with-advanced-graph-neural-networks/ |
| Uber | Engine tìm đường + lớp hiệu chỉnh ETA bằng lịch sử chuyến ở trên; điểm yếu cold start ở thành phố mới | đã tìm | https://www.uber.com/blog/engineering-routing-engine |
| Grab | Tự làm bản đồ vì ĐNÁ thiếu dữ liệu (hẻm, xe máy, tên gọi dân gian); tài xế là "máy đo" gửi dữ liệu; tự công bố lỗi thấp hơn 4 lần so với bên ngoài | đã tìm (báo chí + Grab) | https://www.grab.com/sg/inside-grab/stories/how-grabmaps-knows-the-fastest-routes-in-southeast-asia/ · https://www.frontier-enterprise.com/uncharted-no-more-how-grab-built-its-mapping-tool-grabmaps/ · https://www.theregister.com/2022/06/09/grab_maps_as_a_service/ |
| Mapbox | Giao thông là lớp tile riêng chồng lên nền, làm mới ~8 phút; dữ liệu từ SDK điện thoại | đã tìm | https://docs.mapbox.com/data/tilesets/reference/mapbox-traffic-v1/ |
| Waze | Người dùng báo sự cố, hệ thống gộp và xác thực rồi đưa vào tìm tuyến | nhớ | — |
| Apple Maps | Làm lại dữ liệu bản đồ riêng | nhớ | — |

Bức tranh chung: hệ bản đồ lớn có 3 mặt phẳng: **làm bản đồ** (chậm, ra phiên bản), **phục vụ** (tile, tuyến, tìm kiếm), **vòng sống** (GPS → giao thông → quay lại tuyến). Tile để vẽ và đồ thị tìm đường dựng từ **cùng một phiên bản bản đồ**.

## Phương án tầng 1 agent đề xuất (CHƯA chốt)

**3 app**: khách, tài xế, màn hình vận hành.

**8 khối server**:

| Khối | Trách nhiệm | Có trong repo? |
|---|---|---|
| Nền tảng bản đồ | bản đồ, tìm đường, ETA, giao thông, tình trạng đường | có phần lớn (`server/`) |
| Tìm địa điểm | chữ gõ → điểm trên bản đồ | chưa |
| Vị trí tài xế (cung) | ai online, ở đâu, rảnh/bận | chưa |
| Báo giá | tuyến + cung cầu → giá | chưa |
| Chuyến đi | nguồn sự thật về vòng đời chuyến | chưa |
| Điều phối | chọn tài xế, mời, xử lý từ chối/hết giờ | chưa |
| Kênh thời gian thực | đẩy sự kiện xuống app | chưa |
| Tài khoản, thanh toán, đánh giá | danh tính, tiền, chất lượng | chưa |

**3 luồng**: (A) nhịp tim tài xế → vị trí tài xế + dữ liệu giao thông (một dòng, hai bên dùng); (B) đặt xe: tìm địa điểm → báo giá → tạo chuyến → điều phối (hỏi cung gần + ETA theo đường) → mời qua kênh thời gian thực → trạng thái chuyến → thanh toán → đánh giá; (C) vòng học: ETA thực tế so dự đoán → chỉnh bản đồ và giá.

**5 nguyên tắc**: tách dữ liệu vị trí (nhiều, chóng cũ) khỏi trạng thái chuyến (ít, không được sai); Chuyến đi là nguồn sự thật duy nhất, thao tác gửi lại không bị tính hai lần; điều phối là khách lớn nhất của bản đồ; chia theo thành phố; client hiển thị, server quyết định (khớp `server/ARCHITECTURE_LOCK.md`).

**Grab vs Xanh SM**: Grab là sàn, tài xế đối tác được từ chối → điều phối kiểu *mời*. Xanh SM có đội xe điện riêng, tài xế nhân viên → có thể *giao thẳng*, thêm ràng buộc pin và trạm sạc, chủ động điều xe trống.

**Đánh đổi điều phối**: ghép ngay từng yêu cầu (đơn giản) vs gom vài giây rồi ghép cả loạt (tối ưu tổng). Gợi ý MVP ghép ngay.

**Tóm phương án đưa user chốt**: giữ `server/` làm khối Nền tảng bản đồ, thêm các khối quanh nó; hai app dùng chung renderer `client/map`; MVP gồm một thành phố, một loại xe, chở người, tiền mặt, ghép ngay.

## Quyết định và giới hạn

- [source-observed] Client vẽ tile OpenFreeMap (`client/map/README.md`); server tìm đường trên OSM qua Overpass (`server/FLOW.md`, `server/mapdata/roads/overpass.py`). Hai nguồn, hai phiên bản, không chung mã đường → sẽ vỡ khi tô giao thông hoặc vẽ tuyến khớp đường. Chưa bàn cách xử lý.
- [source-observed] `server/ARCHITECTURE_LOCK.md`: server sở hữu routing, traffic, roadstate, ingest, storage; mobile sở hữu render/UI.
- [source-observed] `server/ingest/gps/probes.py` đã có chỗ nhận GPS probe, chưa có luồng từ app tài xế.
- [source-observed] `sandbox/map_routing/STATUS.md`: sandbox không chạy được sau migration server.

## Sản phẩm hiện hành

- Chỉ có nội dung bàn trong chat và note này. Chưa có HTML architect, chưa research song song, chưa code.
- Phiên chạy trên cloud, không có Obsidian MCP → note này ghi vào bản `agent-system-server/` trong repo, **chưa đồng bộ vào vault** `/home/abel/.secondbrain`.

## Phần còn mở (chờ user trả lời)

1. Mô hình tài xế: Grab (đối tác, được từ chối), Xanh SM (đội xe riêng, pin), hay cả hai?
2. Phạm vi MVP: chỉ chở người, hay thêm giao đồ ăn / giao hàng?
3. Loại xe: xe máy, ô tô, hay cả hai?
4. Quy mô: demo một quận / một thành phố, hay thiết kế sẵn nhiều thành phố?
5. Đồng ý "server hiện tại = khối bản đồ, không đổi ranh giới" không?
6. Xử lý khoảng trống hai nguồn bản đồ (OpenFreeMap vs Overpass) trước hay sau?

Sau khi chốt: bước 2–3 hiến pháp (operator đặc tả khối, HTML sơ đồ theo chuẩn FexMix).
