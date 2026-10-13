# Thiết kế hệ thống agent memory

**Cập nhật:** 08/10/2026. **Mục tiêu:** sau khi bạn yêu cầu lưu một phiên, agent ở phiên sau tìm được bài học liên quan để hiểu đúng mục tiêu, cách làm và chuẩn đầu ra trước khi bắt tay vào việc. Đây là thiết kế hiện hành; những phần ghi “cần xây” chưa hoạt động.

## Quyết định kiến trúc hiện tại

```text
Codex ─────┐
Claude ────┼── bootstrap ngắn → INDEX → note liên quan trong vault Markdown
Obsidian ──┘                     ├─ RULES / SYSTEM / TEMPLATE
                                ├─ sessions / facts / proposals
                                └─ chỉ mục tìm kiếm (chỉ thêm khi cần)
```

`~/.secondbrain/` là nguồn chuẩn; Obsidian là giao diện biên tập. [Obsidian lưu note dạng Markdown](https://obsidian.md/help/data-storage), và [Bases](https://obsidian.md/help/bases) tạo bảng xem/lọc trên Properties. Codex và Claude Code hiện đọc cùng filesystem, nên chưa cần MCP. Nếu agent khác không có quyền tới thư mục này, cần adapter/API có kiểm quyền. SQLite FTS hoặc vector chỉ là **chỉ mục dựng lại từ note**, không phải nơi ghi thứ hai.

## Hai luồng bắt buộc

**Cuối phiên, theo yêu cầu của bạn:** đọc phần hội thoại còn truy cập được và sản phẩm cuối → tạo note phiên → rút mục bền nhỏ → phân biệt `confirmed`/`proposed` và đúng phạm vi → so với mục cũ, thay/supersede nếu cần → cập nhật `INDEX.md` → báo đã ghi gì.

**Phiên mới có task liên quan:** xác định dự án/chủ đề → tìm mục `confirmed` và note phiên nguồn → chọn vài mục cần thiết → đối chiếu code/plan hiện tại → thực hiện task. Khi memory thiếu hoặc cũ, không bịa hay coi note là quyền thực thi. Quy tắc chi tiết ở [RULES.md](RULES.md); định dạng ở [TEMPLATE.md](TEMPLATE.md).

## Trạng thái thực tế

| Đã có | Còn cần xây/kiểm |
|---|---|
| Skill `session-secondbrain` dùng chung cho Codex và Claude Code qua symlink; bootstrap cá nhân của hai runtime; skill trỏ tới quy tắc và mẫu hai tầng trong vault. | Kiểm việc trích xuất, kiểm trùng và supersede trên dữ liệu thật. |
| Vault riêng với `INDEX.md`; Obsidian đã cài trên máy. Bản đồ ba repo `internproj` nằm ở `projects/internproj/` (kiểm 2026-10-09). | Mở vault trong GUI Obsidian khi có desktop; nếu cần, tạo Bases xem mục chờ duyệt. |
| Quy tắc nguồn/phạm vi/trạng thái được viết ở đây; vault đã có note phiên, các fact `confirmed`, bản đồ project, đề xuất và một số hướng dẫn tái sử dụng. | Thử truy xuất và áp dụng ở một phiên mới. |
| Agent cùng máy có thể đọc tệp trực tiếp. | Backup và kiểm phục hồi; adapter cho cloud/máy khác chỉ khi có nhu cầu thực. |

## Kiểm chất lượng trước khi mở rộng

Thử một số task từng phải sửa hướng. Đánh giá: agent ở phiên mới có tìm đúng memory, không áp quy trình sai dự án, dùng bản quyết định mới, tránh lỗi cũ, và biết nói “chưa có dữ liệu” khi không tìm thấy. Đo bằng sản phẩm được bạn chấp nhận ở bản đầu và số correction, không chỉ bằng câu hỏi nhớ fact. [LongMemEval](https://arxiv.org/abs/2410.10813) kiểm cập nhật và suy luận qua nhiều phiên; [LongMemEval-V2](https://arxiv.org/abs/2605.12493) thêm workflow và lỗi môi trường; [LoCoMo-Plus](https://aclanthology.org/2026.acl-long.1150/) chỉ ra giới hạn của phép kiểm chỉ hỏi fact.

Các ca thử tối thiểu: (1) một correction trong phiên cũ được áp vào task mới; (2) quy tắc `intern_project1` không lan sang `project1_server`; (3) mục đổi ý khiến bản cũ hết hiệu lực; (4) suy luận `proposed` không thành chỉ dẫn; (5) không có memory thì agent không bịa.

## Vận hành và mở rộng

- **Duyệt/sửa/xóa:** mỗi mục có ID, nguồn, phạm vi, trạng thái và ngày. Agent chỉ đề xuất suy luận. Note cũ được supersede khi bạn đổi ý; việc xóa trong vault không xóa bản sao ở log/cache bên ngoài.
- **Backup:** cần một bản sao một chiều ngoài vault và thử phục hồi. [File Recovery của Obsidian không thay backup](https://obsidian.md/help/plugins/file-recovery).
- **Ghi đồng thời:** tránh nhiều agent sửa cùng một note; dùng file riêng cho đề xuất, phát hiện phiên bản đổi trước khi ghi. [Obsidian Sync có thể tạo conflict khi nhiều thiết bị cùng sửa](https://obsidian.md/help/sync/troubleshoot).
- **MCP/remote:** chỉ xây khi có agent không đọc được filesystem. Tool đọc lọc theo quyền, dự án và `confirmed`; tool ghi chỉ tạo đề xuất. Nội dung trả từ nguồn ngoài/MCP có thể chứa prompt injection, nên không được nâng thành quy tắc cá nhân. [OpenAI Docs](https://developers.openai.com/api/docs/guides/deep-research).
- **Tìm kiếm nâng cao:** bắt đầu bằng `INDEX.md` + tìm tệp. Thêm FTS/embedding khi bộ task thử cho thấy bỏ sót cách diễn đạt khác nhau. Không cần graph hoặc tự động trích xuất hàng loạt lúc vault còn nhỏ.

## Quyết định còn mở

Hiện mới nối Codex và Claude Code trên máy này. Nếu bạn cần agent khác hoặc máy/cloud, cần xác định runtime và phạm vi dữ liệu được phép chia sẻ trước khi dựng adapter. Hồ sơ mục tiêu, vai trò hay sở thích cá nhân chỉ được thêm khi bạn nêu rõ; quy tắc có sẵn trong từng repo chưa mặc nhiên thành quy tắc toàn cục. Obsidian là giao diện tùy chọn, còn tệp Markdown vẫn dùng được khi không mở GUI.

## Những hệ thống tham chiếu

- [MCP Memory](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md): bản mẫu graph với công cụ CRUD/tìm kiếm.
- [Mem0](https://docs.mem0.ai/core-concepts/how-it-works): `add` sau tương tác, `search` trước phản hồi, trích fact và semantic retrieval.
- [Zep](https://help.getzep.com/v3/agent-memory-solution): context graph theo user/thread và thời gian.
- [Letta](https://docs.letta.com/concepts/stateful-agents): memory bền của một agent qua nhiều cuộc hội thoại.
- [LangGraph Store](https://docs.langchain.com/oss/python/langgraph/add-memory): tách thread state và long-term store theo namespace.

Các hệ thống trên chứng minh mô hình lưu ngoài hội thoại rồi truy xuất theo task; chúng không tự bảo đảm “làm đúng một lần” cho bạn. Bộ thử từ các task của chính bạn mới quyết định có cần kỹ thuật phức tạp hơn hay không.
