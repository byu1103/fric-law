# FRIC LAW Content Studio

Local Streamlit newsroom for a Vietnam law firm writing for investors from China. The Vietnamese dashboard preserves the existing five-step workflow: research → evidence → Simplified Chinese draft → human review → append to one master. It never posts to WeChat.

## Run on macOS

The existing scaffold on this Mac is at the path below; the originally mentioned Downloads path was absent.

```bash
cd "/Users/macbook1/Documents/Job/Fric Law/FRIC_LAW_Content_Studio"
.venv/bin/python run_local.py start --open-browser
```

Có thể nháy đúp `start_mac.command` để khởi động và mở trình duyệt. Máy chủ chạy độc lập với cửa sổ Terminal/phiên chat; bấm mở lại sẽ dùng cùng tiến trình. Ứng dụng không tự khởi động khi bật máy. Nháy đúp `stop_mac.command` để dừng.

Để kiểm tra, khởi động lại hoặc dừng từ Terminal:

```bash
.venv/bin/python run_local.py status
.venv/bin/python run_local.py restart
.venv/bin/python run_local.py stop
```

Log cục bộ nằm trong `.runtime/server.log`; `.runtime/` được loại khỏi Git. Nếu cổng 8501 do ứng dụng khác sử dụng, launcher báo lỗi và không dừng ứng dụng đó. Có thể chọn cổng khác bằng `--port 8502`. Sau khi sửa code, dùng `restart` để nạp lại toàn bộ module Python.

For a clean installation (Python 3.11 or newer):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --index-url https://pypi.org/simple -r requirements-dev.txt
```

The terminal prints the actual local URL. Port 8501 is explicitly selected above; if occupied by an unrelated process, choose an unused port. The launcher never stops an unrelated process. All persistent editorial data defaults to `~/Documents/FRIC_LAW_WeChat_Studio`; override with `FRIC_WORKSPACE` before starting.

## Link dùng thử cho máy khác và hosting 24/7

Chưa có tài khoản hosting: làm theo [hướng dẫn triển khai từng bước](HUONG_DAN_DEPLOY_24_7.md). Thư mục mã sạch đã chuẩn bị tại `~/Documents/FRIC_LAW_Deploy_Source`; thư mục này không chứa khóa, DB hoặc bản thảo.

```bash
cd "/Users/macbook1/Documents/Job/Fric Law/FRIC_LAW_Content_Studio"
.venv/bin/python run_share.py install
.venv/bin/python run_share.py start --vpn-dns
.venv/bin/python run_share.py status
.venv/bin/python run_share.py recover
```

Chỉ chạy `install` lần đầu: tải cloudflared từ bản phát hành chính thức, kiểm tra SHA-256 rồi lưu trong `.runtime/bin`, không cài toàn hệ thống. `start` in URL HTTPS thật. Với VPN của máy này, `--vpn-dns` xác minh các Cloudflare edge qua DNS-over-HTTPS cho riêng tiến trình tunnel, không thay DNS hệ thống và không tắt kiểm tra TLS. Tùy chọn này dùng cờ edge nội bộ của cloudflared, dành cho link dùng thử; mạng bình thường có thể bỏ nó.

Tên đăng nhập và mật khẩu ngẫu nhiên nằm trong `.runtime/share/access.json` với quyền `0600`; không đưa file này vào Git hoặc chat. Link Internet mở màn hình đăng nhập trước khi đọc SQLite/bản thảo. Khóa API chỉ được quản trị từ cấu hình máy chủ, không sửa qua link chia sẻ. Đây là mật khẩu chung của nhóm, chưa phải hệ thống tài khoản riêng cho từng luật sư/biên tập viên. Phiên hết hạn sau 8 giờ và có giới hạn số lần thử đăng nhập.

Link tạm dùng cổng loopback 8502 qua tunnel, cùng workspace SQLite/MASTER đang có. Giữ Mac thức, có Internet và các tiến trình còn chạy; không tự khởi động sau reboot, URL đổi khi tạo lại tunnel và không có bảo đảm uptime. Chạy `.venv/bin/python run_share.py stop` để thu hồi link, vẫn giữ ứng dụng local 8501. Sau khi sửa module Python, dùng `run_share.py restart --vpn-dns` để nạp bản mới. Launcher chỉ báo thành công sau khi tunnel đã đăng ký kết nối; URL được cấp nhưng chưa kết nối không được coi là hoạt động.

Nếu gặp Cloudflare **1033**, dùng `recover` trước: lệnh chờ kết nối lại, giữ connector/URL/mật khẩu đang có và chỉ khởi động lại backend thuộc ứng dụng khi cần. `status` và `start` kiểm tra cả URL công khai phải trả HTTP 200 với nội dung `ok`, đồng thời phân biệt lỗi backend, connector và đường truy cập ngoài Internet. Chúng không tự tạo link khác khi kiểm tra công khai thất bại. Nếu connector cũ đã dừng, `recover` báo không giữ được URL; lúc đó tạo phiên mới bằng `start --vpn-dns`. Quick Tunnel vẫn có thể ngắt do mạng hoặc dịch vụ; kiểm tra thành công tại một thời điểm không bảo đảm uptime.

Để chạy độc lập với Mac 24/7, đã có Dockerfile, Compose, Render Blueprint một instance và disk bền vững. Xem [hướng dẫn triển khai](deploy/README.md). Chưa tạo cloud service hoặc phát sinh tài nguyên tính phí; cần tài khoản hosting để hoàn tất. SQLite/MASTER phải nằm trên persistent disk. Chỉ truy cập bằng link trong Chrome không cần Google lập chỉ mục khu vực biên tập.

Tìm kiếm hoạt động ngay mà không cần API key. Mặc định **Tự động** dùng RSS và mục tin công khai của các báo/cơ quan đã chọn khi chưa có Tavily. Nguồn công khai chỉ bao phủ các mục đang được website công bố, không phải toàn bộ kho tin lịch sử.

`TAVILY_API_KEY` là tùy chọn cho tìm kiếm; `AIBOX_API_KEY` dùng riêng cho AI soạn bài trên website. Bản local có thể lưu khóa trong **Kết nối & thư mục làm việc** hoặc phần kết nối AI bên dưới. Khóa được lưu nguyên tử trong `.env` với quyền 0600; ô nhập không hiện lại khóa đã lưu. `.env`, tệp tạm và log được loại khỏi Git. Không gửi khóa qua chat.

Cũng có thể tự tạo `.env` từ `.env.example` nếu chưa có, rồi cấu hình trên máy. `AIBOX_MODEL` là model khả dụng trong tài khoản AI Box. Website chỉ dùng endpoint cố định `https://api.ai-box.vn/v1/chat/completions`, không gọi Responses API hoặc tự chuyển sang nhà cung cấp khác khi lỗi.

Tài liệu Codex CLI đính kèm là tài liệu tham khảo cách tích hợp nhà cung cấp. Không áp dụng các bước sửa `~/.codex/config.toml` hay catalog model toàn máy. Khóa/endpoint/model của website tách khỏi tài khoản, đăng nhập và quota ChatGPT/Codex của cuộc chat. `OPENAI_API_KEY`, `OPENAI_MODEL` hoặc `OPENAI_BASE_URL` của công cụ khác không kích hoạt hay điều hướng AI của website.

## Kết nối AI soạn thảo

1. Đăng nhập [AI Box](https://home.ai-box.vn/), mở mục **API Keys** và tạo khóa riêng. Kiểm tra số dư, hạn mức và model được phép dùng. Không cần đổi cấu hình hay đăng nhập Codex để kết nối website.
2. Trên Mac quản trị, mở `http://127.0.0.1:8501` → **Soạn & duyệt → Kết nối AI Box**. Nhập khóa trong ô mật khẩu và model thực sự được tài khoản AI Box cung cấp, rồi bấm **Lưu kết nối AI**. Tên model trong tài liệu chỉ là ví dụ; kiểm tra danh sách hiện có trước khi chọn.
3. Bấm **Kiểm tra kết nối AI**. Chỉ nút này mới gửi một yêu cầu API nhỏ, có thể phát sinh phí; không gửi nguồn/bản thảo. Lưu một khóa chỉ được ghi là đã cấu hình, chưa phải đã kết nối. Thay khóa/model làm mất trạng thái kiểm tra cũ. Không tự gọi API khi mở trang.
4. Sau khi kết nối, chọn nguồn có văn bản đủ dài và chuyên mục rồi bấm **AI soạn bài tiếng Trung**. Chuyên mục pháp lý cần nguồn chính thức. AI tạo bản nháp chưa được xác minh; vẫn cần đối chiếu và đủ hai phê duyệt trước xuất tài liệu.

Khóa/model mới áp dụng trên lần render tiếp theo, không cần restart server. Ở link HTTPS chia sẻ, người biên tập bấm **Đọc lại cấu hình AI** sau khi quản trị viên lưu trên Mac. Link chia sẻ không cho thay khóa hoặc model. Khi triển khai cloud, quản trị viên đặt `AIBOX_API_KEY`/`AIBOX_MODEL` trong mục secret/environment của hosting; bản cloud không ghi khóa qua giao diện.

Cách thay thế trên Mac: nháy đúp `connect_ai_mac.command`, hoặc chạy trong Terminal:

```bash
cd "/Users/macbook1/Documents/Job/Fric Law/FRIC_LAW_Content_Studio"
.venv/bin/python setup_ai.py
```

CLI nhận khóa bằng nhập ẩn, không nhận khóa trong đối số. Nếu Terminal không hỗ trợ nhập ẩn, công cụ dừng mà không đọc khóa dưới chế độ hiện chữ. `--no-test` chỉ lưu; `--check-only` chỉ kiểm tra cấu hình đã có. Không chạy CLI bằng `echo`/pipe chứa khóa. CLI không in khóa ra kết quả hoặc lỗi.

Lỗi AI được phân loại rõ: khóa sai/thu hồi, thiếu quyền, model không có, hết tín dụng/giới hạn chi tiêu, giới hạn tốc độ, mạng/VPN, timeout hoặc lỗi dịch vụ. Lỗi và phản hồi trống/từ chối/chưa hoàn tất không ghi đè bản thảo đang viết. SDK OpenAI chỉ là thư viện giao tiếp; yêu cầu chỉ gửi tới AI Box. Giữ giới hạn thời gian/độ dài, không tự gửi lại và không theo redirect sang máy chủ khác. Không bao giờ coi đầu ra AI là chứng cứ pháp lý độc lập.

Kết quả kiểm tra trực tiếp ngày 23/10/2026: AI Box trả HTTP **503** với mã **`model_not_found`** cho `deepseek-v4.1-flash`, do không có kênh khả dụng trong nhóm **`Vip (distributor)`** của khóa đang cấu hình. Thông báo cũ “Dịch vụ AI Box đang gặp sự cố” chưa thể hiện đúng nguyên nhân; ứng dụng hiện phân loại trường hợp này thành **`model_unavailable`**, giải thích nhóm/quyền model và hiển thị mã yêu cầu an toàn để đối chiếu với AI Box. Chưa xác nhận sinh văn bản thành công. Quản trị viên cần kiểm tra nhóm của API key và nhờ AI Box mở kênh hoặc xác nhận một model thực sự sinh được văn bản; thử lại nhiều lần không sửa được cấu hình quyền/kênh này.

HTTP 200 từ **`GET /v1/models`** chỉ chứng minh đọc được danh sách model, chưa chứng minh model có kênh sinh văn bản cho khóa hiện tại. Chỉ coi AI sẵn sàng sau khi yêu cầu sinh văn bản tối thiểu trong **Kiểm tra kết nối AI** thành công. Website vẫn chỉ dùng AI Box, không tự đổi model, không dùng khóa/quota ChatGPT/Codex và không gửi lại nguồn khi gặp lỗi. Xem [hồ sơ kiểm tra kênh AI Box](AI_BOX_KIEM_TRA_KENH.md) để biết thông tin cần đối chiếu với nhà cung cấp; không kèm khóa API hoặc nội dung nguồn/bản thảo khi liên hệ.

Kiểm tra lại ngày **24/10/2026**: cả `deepseek-v4.1-flash` và `deepseek-v4-pro-0813` trong danh sách của khóa đều tiếp tục trả HTTP 503/thiếu kênh khi kiểm tra sinh văn bản tối thiểu. Chưa xác nhận model nào hoạt động. Khi lỗi này xuất hiện, phần kết nối có liên kết quản lý API Keys, thông tin kỹ thuật để sao chép gửi hỗ trợ và thời điểm phản hồi theo giờ Việt Nam. Hướng dẫn tạo khóa mới chỉ hiện khi chưa cấu hình; tạo khóa khác cùng nhóm chưa chắc sửa được kênh. Trạng thái cũ trong phiên chưa có thời điểm được ghi rõ. Hiển thị lại trang không tự gửi yêu cầu API.

Chỉ thao tác **Kiểm tra kết nối AI** hoặc **AI soạn bài tiếng Trung** mới gửi yêu cầu. Việc soạn bài gửi style guide, ghi chú biên tập và các nguồn đã chọn tới nhà cung cấp AI Box theo lựa chọn của người dùng. Không đưa thông tin khách hàng bí mật vào ghi chú. Không cam kết chính sách lưu dữ liệu của nhà cung cấp từ tính tương thích SDK; vẫn cần người biên tập duyệt trước xuất bản.

## Research and dates

- One prominent search, category chips, priority-source selector and inclusive dates. Default is **today minus six days through today in Asia/Ho_Chi_Minh**.
- Priority sources include Chính phủ legal documents, Công báo, Chính phủ, VBPL, MOF, SBV, ThuVienPhapLuat, CafeF, VnExpress, VietnamPlus and Báo Đầu tư. The allowlist is in `research.py`.
- Chế độ Tự động ưu tiên Tavily nếu đã có khóa; khi Tavily lỗi sẽ chuyển sang nguồn công khai và hiển thị cảnh báo. Có thể chọn riêng Nguồn công khai hoặc Tavily. RSS và mục tin chỉ cung cấp URL ứng viên. Tavily also returns candidate URLs. Provider publication estimates, indexing dates and update dates do **not** establish original publication. Each candidate is checked against explicit original-publication metadata on its page. Conflicting dates, unsupported formats, inaccessible pages and PDFs enter a separate **needs verification** queue. Proven out-of-range originals are excluded from the recent shortlist.
- CafeF semantic publication spans and known original header labels on Báo Đầu Tư are supported. Short legal document IDs and Chinese headings remain in extracted article text; the parser prefers the actual article body over navigation/related stories.
- Same-page `www` aliases and HTTP→HTTPS upgrades are accepted only after revalidating the allowlist and DNS. A redirect to a different article/site, HTTPS downgrade, private host or arbitrary IP remains blocked.
- On this Mac, the VPN returns benchmark addresses in `198.18.0.0/15` and ULA IPv6. Exact registered publisher hosts can be corroborated through Google Public DNS over HTTPS before retrieval. Ordinary loopback, RFC1918 and link-local addresses remain blocked. No operating-system DNS/VPN settings are changed.
- DNS chỉ cache xác nhận thành công; lỗi tạm thời được thử lại ngay. Bộ đọc thử lại một lần với lỗi kết nối/502/503 trong giới hạn thời gian. Cảnh báo phân biệt tên miền không đọc được với một mục RSS lỗi của tên miền vẫn có dữ liệu. **Chi tiết kết nối từng nguồn** hiển thị endpoint, trạng thái và nguyên nhân DNS/TLS/timeout/HTTP/chặn truy cập/trang cần JavaScript. Không coi nguồn chặn hoặc mục tin rỗng là đã đọc thành công.
- Publication timestamps with offsets are converted to Vietnam calendar dates; ambiguous dates are left unverified. Page metadata is evidence of a date, not verification of the article's claims.
- Manual date confirmation requires the original date, a description/excerpt of its proof and reviewer identity. Changing a date revokes its earlier date proof unless explicitly re-attested.
- Issuance, effective date, authority, document number, article/section, amendment status and an amendment/status-check URL are **separate legal fields**. Empty fields stay visibly missing. No law text or legal citation is invented or inferred from a news date.
- Conservative grouping retains each original URL; distinct legal document numbers remain separate. Transparent ranking uses relevance to investors from China, regulation, capital flows, M&A, projects, official sources and date proof. Novelty means the URL is new to the local library; it does not claim the event is historically unprecedented.

## Draft and review

`STYLE_GUIDE.md` governs Chinese voice, numbered sections, investor implications, legal advice/disclaimer and original links at the end. One topic is confirmed during review. Source text is passed to AI as evidence, never as instructions. The reference folder was absent during this implementation; place any `.docx` examples in `~/Documents/FRIC_LAW_WeChat_Studio/references/` for subsequent style review. Examples are not legal authority, and the app does not silently treat their content as verified law.

Every saved revision freezes the ordered source list and source text. `[S1]` numbering follows that order. Each sentence and heading is presented for human review, including the headline. The review record identifies the reviewer and either:

- stores an exact excerpt from a cited saved source, with a human attestation that the excerpt supports the claim; or
- labels the unit non-factual analysis/recommendation. Detected legal rules or numerical statements cannot use this shortcut.

Official support, press support, analysis and unreviewed status are shown separately. A legal-rule claim requires a source designated as an official **legal text**, with all legal fields completed; an official news briefing alone is insufficient. Exact-quote matching does not establish entailment or current legal effect: those judgments remain with the reviewer. The sentence splitter and legal-pattern rules are conservative aids, not a semantic fact checker. The editor and lawyer must check all content, topic scope, citations, current amendments and transitional rules.

Two named role sign-offs—editor and lawyer—are required before either export. Roles are local attestations, not authenticated professional credentials. Saving a changed title, body, source order, source evidence or client confirmation invalidates the prior review packet. Changing a claim review also revokes sign-offs. Export functions enforce this policy directly, including calls outside the UI. Legacy checkbox approvals are not grandfathered into export permission. Saved revisions and past sign-offs remain auditable in SQLite.

FRIC LAW project participation claims require a real client-confirmation record (person/date/file reference). Pattern matching cannot establish whether a firm advised a project; the lawyer/editor remains responsible for detecting and removing unsupported claims.

## One Word master

Approved articles append to:

```text
~/Documents/FRIC_LAW_WeChat_Studio/FRIC_LAW_WeChat_MASTER.docx
```

The app never creates a separate Word file per article. It serializes edits/exports and locks the master, writes a temporary file, then atomically replaces the master with the appended version. Older article content and existing document styles are preserved. Original URLs are Word hyperlinks. Article IDs and normalized content fingerprints protect retries and the same article saved under a new ID. If the file succeeds but SQLite fails, the next attempt reconciles its marker without appending again. A missing or mismatched previously recorded master fails closed for recovery. Near-duplicates with substantive wording changes still need editorial review. Back up the workspace regularly; local DB/files do not replace backups.

Exported revisions are immutable. A correction is a new reviewed article appended after the original. Source changes after export do not rewrite the approved historical snapshot. The download button returns the entire existing master.

## Optional Google master

Enable Google Docs API and Drive API, obtain an OAuth Desktop Client and save its JSON locally at:

```text
~/Documents/FRIC_LAW_WeChat_Studio/google_oauth_client.json
```

On an approved article select Google sync and complete browser consent. The app uses one folder and one Google Doc, `drive.file` plus Docs scopes. Token and sync-state files use atomic writes and restrictive permissions. They are ignored by Git along with `.env` and SQLite files.

Sync persists completed creation steps, resumes a pending folder move, rejects ambiguous name matches, and stops when configured resources cannot be read. An uncertain creation outcome is reconciled by discovery or requires a manually confirmed ID; it is never blindly created again. Appends use Google revision control and both article and content markers; a lost write response is checked remotely before local success is recorded. Concurrent remote editing may require retry. Google OAuth consent, actual permissions, remote service behavior and end-to-end sync require a live account and remain separate from mocked tests. The app does not automatically use the user's connected Codex Google account.

## Optional visuals

Maps require an explicitly supplied latitude/longitude, a reviewed allowed-source URL and a coordinate-verification attestation. There is no prefilled project location. Source attribution remains clickable. Fact cards require editorial review, render source attribution and save a provenance sidecar. Long text is rejected rather than silently truncated. These are informational graphics; any future generated illustration must explicitly say it is conceptual and not an actual project rendering. No generative project imagery is produced by this app.

## Validation

```bash
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m compileall -q app.py core.py ai_client.py research.py public_search.py publication_dates.py settings.py setup_ai.py run_local.py run_share.py access_control.py google_docs_sync.py visuals.py deploy tests
python -m unittest discover -s tests -v
```

Tests use isolated temporary workspaces, synthetic evidence and mocked external requests. They exercise publication provenance/date edges, conservative grouping, claim coverage and exact quotes, two-role approval, revision invalidation, Word deduplication and crash recovery, Google creation/move/write failures, map/card validation and an actual Streamlit AppTest editorial workflow. No test sends a real article to Google or WeChat. See `VALIDATION.md` for the exact checks run for this change.
