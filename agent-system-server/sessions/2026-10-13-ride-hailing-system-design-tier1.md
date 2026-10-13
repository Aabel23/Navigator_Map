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
- Sau khi trả lời 5 câu hỏi, user đưa ảnh mục tiêu (Map4D, 3D Quận 1) → hướng nhìn thị giác là bản đồ 3D cách điệu, không chỉ bản đồ phẳng.

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

## Vòng 2: user trả lời 5 câu hỏi (2026-10-13)

- [user-confirmed] **Mô hình đối tác**: ta cung cấp dịch vụ map và phân công việc cho tài xế (kiểu Grab, không phải đội xe riêng kiểu Xanh SM).
- [user-confirmed] **MVP chỉ gồm map + định vị + chỉ đường.** Các dịch vụ khác (báo giá, điều phối, chuyến đi, thanh toán…) bàn và phát triển sau. Trên nền map/định vị/chỉ đường mới tới stage xây app chở người.
- [user-confirmed] **Xe máy trước, ô tô sau**; có thể độc lập với nhau; cơ chế giữa hai loại cần bàn thêm; mục tiêu cuối là cả hai.
- [user-confirmed] **Demo một quận.**
- [user-confirmed] **`server/` hiện tại = khối Nền tảng bản đồ, không đổi ranh giới.**
- Fact bền: [facts/navigator-map-tier1-decisions.md](../facts/navigator-map-tier1-decisions.md).

## Vòng 2: microservice hay không (agent đề xuất, CHƯA chốt)

- Đề xuất **modular monolith**: một server, module ranh giới cứng; chỉ tách service khi có lý do cụ thể. Lý do: một đội, một quận, một chức năng; microservice tốn chi phí mạng, dữ liệu rải rác, vận hành phức tạp = overengineer.
- [source-observed] `server/` đã là modular monolith, có `server/tests/test_dependency_rules.py` chặn import sai ranh giới.
- Case study (mức: nhớ, chưa kiểm nguồn): Uber tách hàng nghìn service rồi gom lại theo miền; Segment và Prime Video (Amazon) quay về một khối; Shopify giữ modular monolith ở quy mô lớn.
- Ba điểm tách tương lai: (1) dựng bản đồ (lô, nặng) tách khỏi phục vụ, khi phủ cả thành phố; (2) nhận vị trí tài xế, khi hàng nghìn tài xế online; (3) kênh thời gian thực + chuyến đi/điều phối, khi có app chở người.
- Xe máy và ô tô: đề xuất **A. một bản đồ, nhiều hồ sơ xe** (chung dữ liệu đường, mỗi loại xe bộ luật riêng; giao thông tách theo loại xe vì xe máy luồn được). MVP chỉ bật hồ sơ xe máy, chừa đúng một chỗ gắn ô tô. Phương án B (hai hệ độc lập) bị đánh giá dễ lệch dữ liệu.
- Tóm phương án chờ chốt: modular monolith, giữ `server/` làm khối bản đồ; MVP map + định vị + chỉ đường xe máy, một quận; một bản đồ nhiều hồ sơ xe; chỉ tách service khi gặp 3 điểm trên; việc tiếp theo là một nguồn bản đồ chung cho vẽ và tìm đường.

## Vòng 3: research ảnh mục tiêu Map4D (2026-10-13)

User đưa ảnh 2 màn hình Map4D (IOTLink) ở trung tâm Quận 1: nhà 3D có texture, Bitexco, chợ Bến Thành, cây dọc đường, vạch làn và mũi tên trên đường, tên đường nằm phẳng trên mặt đường, camera nghiêng. Yêu cầu: tìm phương pháp vẽ và nguồn data.

**Nguồn công khai (đã tìm):** Map4D có 2D/3D/4D (4D = so sánh hiện trạng theo thời gian); hiển thị trên OpenGL; phủ 63 tỉnh; có chứng nhận Cục Đo đạc, Bản đồ và Thông tin địa lý VN; SDK Android/iOS/JS/Flutter trên GitHub, mẫu JS có lớp phủ three.js và deck.gl. **IOTLink không công bố cách làm dữ liệu 3D** (không thấy drone, BIM hay quy trình dựng).

**Bóc lớp (agent suy ra từ ảnh, chưa xác nhận):**

| Lớp | Cách vẽ | Dữ liệu |
|---|---|---|
| Nhà thường (~90%) | đùn đa giác chân nhà theo chiều cao + texture mặt tiền theo loại nhà | chân nhà, chiều cao, loại nhà |
| Công trình biểu tượng | mô hình 3D dựng tay, đặt như vật thể | dựng thủ công từng công trình |
| Cây | một mô hình vẽ lặp hàng nghìn lần, sinh dọc mép đường | sinh tự động |
| Đường | vạch làn, mũi tên sinh từ số làn và hướng rẽ | thuộc tính làn |
| Tên đường | nhãn gắn mặt đất, nghiêng theo camera | tên đường |
| Nền, nước, công viên | màu phẳng như renderer hiện tại | như hiện tại |

Kết luận: bản đồ **3D cách điệu** (trường phái Apple Maps), không phải photogrammetry kiểu Google Earth → làm được với đội nhỏ.

**Khoảng cách với engine (source-observed):**
- Camera chỉ có `worldX, worldY, zoom` (`client/map/ui/static/app.js`), chưa có góc nghiêng và góc xoay.
- `client/map/ui/static/gl.js:545` tắt depth test → chưa vẽ được khối 3D che nhau.
- Lớp `building` tô phẳng một màu (`client/map/config/style.py:66`), chưa đọc chiều cao.
- Lợi thế (nhớ, chưa kiểm trên tile thật): lớp building của schema OpenMapTiles có `render_height`, `render_min_height` → đùn khối không cần thêm nguồn.

**Nguồn dữ liệu miễn phí cho một quận:**

| Cần | Nguồn | Mức kiểm |
|---|---|---|
| Chân nhà và chiều cao | lớp building trong tile OpenFreeMap (từ OSM); nhiều nhà Q1 thiếu chiều cao → đoán theo loại | nhớ |
| Chân nhà và chiều cao đầy đủ hơn | Overture Maps (gộp OSM, Microsoft, Google) | nhớ |
| Chiều cao ước lượng ĐNÁ | Google Open Buildings 2.5D (cần kiểm có phủ VN) | nhớ, chưa kiểm |
| Công trình biểu tượng | tự dựng (Blender) ~20–30 công trình Q1; không lấy từ Google 3D Tiles vì điều khoản cấm trích xuất | nhớ |
| Cây, làn đường | OSM (cây thưa, số làn ở trục chính) + sinh tự động | nhớ |
| Texture mặt tiền | tự làm 5–10 texture (nhà phố, chung cư, văn phòng kính, mái ngói) | suy luận |

**Lộ trình đề xuất (chưa chốt):** (1) 2.5D: camera nghiêng/xoay, đùn nhà, đổ bóng theo hướng mặt, ước ~70% dáng ảnh; (2) làm đẹp tự động: texture mặt tiền, cây, vạch làn, tên đường phẳng trên mặt đường; (3) lớp công trình biểu tượng dựng tay.

**Nguồn:**
- https://github.com/Map4D · https://github.com/Map4D/map4d-android-sdk · https://github.com/Map4D/js-samples (đã mở)
- https://iotlink.com.vn/map-4d/ · https://iotlink.com.vn/ban-do-so-map4d-tu-hao-ban-do-3d-thuan-viet/ · https://iotlink.com.vn/map4d-la-gi-tai-sao-nen-dung-ban-do-so-viet-nam/ (đã tìm)
- https://quantrimang.com/viet-nam-da-co-ban-do-4d-172324 · https://vietnamnet.vn/en/first-vietnamese-made-real-4d-digital-map-platform-launched-686889.html · https://vov5.vov.gov.vn/make-in-vietnam/map4d-digital-map-for-the-vietnamese-2095535.vov5 (đã tìm)
- https://docs.maptiler.com/deck-gl/examples/mvt-extrude/ (đã tìm; ví dụ đùn khối dùng `render_height`)

## Phần còn mở (chờ user)

1. Chốt phương án vòng 2: modular monolith + một bản đồ nhiều hồ sơ xe.
2. Xử lý khoảng trống hai nguồn bản đồ (OpenFreeMap vs Overpass) trước hay sau; nên quyết cùng lúc với 3D vì cùng đụng dữ liệu tòa nhà.
3. Thứ tự 3D so với chỉ đường: trước, song song hay sau (agent nghiêng về chỉ đường trước).
4. Thiết bị demo: điện thoại hay trình duyệt máy tính (ảnh hưởng hiệu năng 3D).

Sau khi chốt: bước 2–3 hiến pháp (operator đặc tả khối, HTML sơ đồ theo chuẩn FexMix).
