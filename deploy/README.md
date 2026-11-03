# Triển khai FRIC LAW Content Studio

Nếu chưa có hosting, bắt đầu bằng [hướng dẫn từng bước GitHub + Render](../HUONG_DAN_DEPLOY_24_7.md) và thư mục mã sạch `~/Documents/FRIC_LAW_Deploy_Source`.

Ứng dụng có thể mở bằng Google Chrome trên máy khác khi có URL HTTPS. Điều này khác với việc xuất hiện trong kết quả Google Search. Studio chứa bản thảo và công cụ phê duyệt nên yêu cầu đăng nhập; không đưa dữ liệu biên tập lên trang công khai để Google lập chỉ mục.

Các tệp ở đây chuẩn bị cho hosting lâu dài. Chưa tạo tài khoản, tài nguyên tính phí, tên miền hay dịch vụ Render. URL tunnel tạm thời, nếu đang dùng, vẫn phụ thuộc vào máy Mac và kết nối mạng của máy đó.

## Chia sẻ HTTPS tạm thời từ Mac

Từ thư mục gốc dự án:

```bash
.venv/bin/python run_share.py install
.venv/bin/python run_share.py start --vpn-dns
.venv/bin/python run_share.py status
.venv/bin/python run_share.py recover
```

Launcher tải cloudflared chính thức và kiểm tra SHA-256, mở một tiến trình Streamlit có đăng nhập riêng ở cổng 8502, rồi in URL HTTPS thực tế. Ứng dụng cục bộ tại cổng 8501 vẫn hoạt động. `--vpn-dns` dùng tra cứu DNS riêng cho tunnel khi VPN chặn DNS của cloudflared; không thay đổi cấu hình mạng hệ thống. Khi không cần xử lý VPN, có thể dùng `start` không kèm cờ này.

Tên đăng nhập và mật khẩu tự tạo nằm trong `.runtime/share/access.json`, chỉ chủ tài khoản Mac có quyền đọc. Mở tệp bằng trình soạn thảo trên Mac; không dán nội dung vào chat, Git hoặc log. Người được phép truy cập cần URL và thông tin đăng nhập qua kênh riêng. Đây là studio có mật khẩu để mở trong Chrome, không phải trang nội dung để Google Search lập chỉ mục.

Giữ Mac thức và có Internet. URL thay đổi khi tạo tunnel mới; không có bảo đảm uptime.

Khi có lỗi 1033/mất kết nối, dùng `recover` để chờ connector tự nối lại và kiểm tra URL công khai, giữ nguyên URL/mật khẩu. Lệnh không tạo lại tunnel hoặc dừng tiến trình khác. Nếu connector đã chết thì URL cũ không thể khôi phục qua lệnh này; cần `start --vpn-dns` để tạo phiên mới. `status/start` kiểm tra cả HTTPS công khai, không chỉ tiến trình hoặc cổng local. Điều này cải thiện chẩn đoán, không biến Quick Tunnel thành hosting có bảo đảm uptime.

Để dừng chia sẻ mà vẫn giữ app cục bộ:

```bash
.venv/bin/python run_share.py stop
```

Tìm hiểu giới hạn tại [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). Dùng hosting có disk dưới đây nếu cần chạy lâu dài khi Mac tắt.

## Docker trên máy chủ

Yêu cầu Docker Engine/Desktop và Docker Compose. Chạy lệnh trong thư mục gốc dự án. Python ảo hiện có dùng để tạo hash mật khẩu; mật khẩu được hỏi bằng ô nhập ẩn và không đưa vào lịch sử lệnh.

```bash
umask 077
mkdir -p .runtime
.venv/bin/python -m access_control hash > .runtime/deploy-access.hash
```

Sau khi tạo hash thành công, tạo cấu hình riêng. Đoạn sau không ghi đè cấu hình đã có và không in hash:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from unittest.mock import patch
import os
from access_control import load_access_config

encoded = Path('.runtime/deploy-access.hash').read_text().strip()
with patch.dict(os.environ, {'FRIC_ACCESS_PASSWORD_HASH': encoded}, clear=True):
    load_access_config()
with Path('.env.deploy').open('x', encoding='utf-8') as output:
    os.chmod('.env.deploy', 0o600)
    output.write("FRIC_ACCESS_PASSWORD_HASH='" + encoded + "'\n")
PY
docker compose --env-file .env.deploy up --build -d
docker compose --env-file .env.deploy ps
```

Mở `http://127.0.0.1:8502` trên máy chạy Docker. Tên đăng nhập mặc định là `editor`; mật khẩu là giá trị vừa nhập. Cổng Compose chỉ bind loopback để đặt sau reverse proxy HTTPS hoặc tunnel. Không tắt bảo vệ CORS/XSRF để xử lý lỗi proxy; proxy phải chuyển tiếp WebSocket của Streamlit.

Khóa Tavily/AIBox là tùy chọn và được truyền lúc chạy. Khi cần, thêm `TAVILY_API_KEY`, `AIBOX_API_KEY`, `AIBOX_MODEL` vào `.env.deploy` bằng trình soạn thảo trên máy chủ; giữ quyền `0600`. Website chỉ dùng endpoint bên thứ ba `https://api.ai-box.vn/v1` với định dạng Chat Completions. Model mặc định là `deepseek-v4.1-flash`, có trong danh sách model đọc được của khóa hiện tại; quyền và tình trạng phục vụ từng tài khoản vẫn cần kiểm tra trước khi soạn. Chỉ khi bấm kiểm tra hoặc soạn AI, ứng dụng mới gửi yêu cầu tương ứng tới AIBox; việc soạn AI gửi hướng dẫn và nguồn đã chọn. Không chạy lệnh hiển thị toàn bộ cấu hình môi trường khi báo lỗi. `.env.deploy` và `.runtime/` đã được loại khỏi Git. Tìm kiếm công khai vẫn hoạt động khi chưa có khóa.

Khóa và model AIBox chỉ phục vụ website này. Chúng không đổi nhà cung cấp, model, tài khoản hay hạn mức của cuộc chat Codex. Không sửa `~/.codex/config.toml`, token Codex hoặc cấu hình AI toàn máy để kết nối website. Biến `OPENAI_API_KEY`/`OPENAI_MODEL` cũ không được dùng làm thông tin đăng nhập cho website; không cần xóa hoặc thay chúng trong môi trường của công cụ khác. Địa chỉ API bị cố định trong adapter, không nhận URL tùy ý từ `.env`.

Image dùng Python 3.13, font Noto CJK và tài khoản UID/GID `10001`. Mã nguồn `/app` không ghi được bởi tài khoản chạy ứng dụng. Volume `studio_data` giữ SQLite, MASTER Word và hình tại `/data`. Chạy đúng **một instance**; không dùng `--scale` hoặc nhiều container cùng bộ dữ liệu. Không dùng `docker compose down --volumes` khi cần giữ dữ liệu.

Đọc [hướng dẫn Docker của Streamlit](https://docs.streamlit.io/deploy/tutorials/docker) và [cách truyền biến môi trường của Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## Render với ổ đĩa bền vững

1. Đăng nhập Render và kết nối repository chứa mã nguồn, ưu tiên repository riêng tư. Chỉ đưa mã nguồn vào Git; không đưa `.env`, cơ sở dữ liệu, tài liệu khách hàng hoặc OAuth token.
2. Tạo Blueprint từ `render.yaml`. Cấu hình dùng một Docker web service tại Singapore và disk `/data` 1 GB. Đây là tài nguyên **có phí**; kiểm tra bảng tính phí của Render trước khi xác nhận tạo.
3. Khi Render hỏi `FRIC_ACCESS_PASSWORD_HASH`, dùng hash đã tạo ở trên. Trên macOS có thể dùng `pbcopy < .runtime/deploy-access.hash` để sao chép trực tiếp vào trường bí mật của Render mà không in ra Terminal. Đặt `AIBOX_API_KEY` hoặc `TAVILY_API_KEY` tùy chọn trong mục Environment khi cần; `AIBOX_MODEL` đã có mặc định trong Blueprint. Không đưa khóa API vào YAML.
4. Xác nhận deploy. Truy cập URL HTTPS thực tế được Render hiển thị, kiểm tra màn hình đăng nhập rồi thử tìm kiếm. Không đoán trước tên miền `onrender.com`.
5. Sau mỗi cập nhật mã, deploy thủ công và kiểm tra lại. Blueprint tắt auto-deploy, đặt đúng một instance; disk được giữ qua các lần deploy nhưng sẽ có một khoảng dừng khi thay instance.

`deploy/entrypoint.py` nhận `PORT`, kiểm tra cấu hình đăng nhập và khả năng ghi workspace trước khi chạy Streamlit ở `0.0.0.0`. Thiếu cấu hình sẽ dừng trước khi mở ứng dụng. Nếu host gắn disk với UID khác, quản trị viên phải cấp quyền cho UID/GID `10001`; launcher không tự đổi quyền toàn bộ dữ liệu.

Tham khảo [Render Blueprint](https://render.com/docs/blueprint-spec), [persistent disks](https://render.com/docs/disks) và [port binding](https://render.com/docs/web-services#port-binding). Không dùng ổ đĩa tạm của hosting miễn phí để giữ SQLite/MASTER.

## Dữ liệu, xác thực và Google

- Hosting khởi tạo workspace mới. Không tự tải bản thảo, `.env` hay tài liệu từ Mac lên cloud. Khi cần di chuyển dữ liệu cũ, dừng ghi trên cả hai máy, sao lưu và chuyển workspace qua kênh quản trị bảo mật; kiểm tra số bài và MASTER trước khi mở lại.
- Sao lưu workspace định kỳ ra nơi độc lập với disk hosting. Với SQLite đang chạy, dùng SQLite backup API hoặc dừng ứng dụng trước khi sao chép. Giữ bản sao trước mọi thao tác khôi phục.
- Mật khẩu đăng nhập chung bảo vệ studio; các xác nhận vai trò luật sư/biên tập viên vẫn là hồ sơ duyệt bài, chưa phải hệ thống tài khoản theo từng người. Bản deploy khóa chỉnh sửa API key trong giao diện; quản trị viên thay khóa qua cấu hình host.
- Ngoài biến hash, có thể gắn file hash bí mật lúc chạy và đặt `FRIC_ACCESS_HASH_FILE`. File phải đọc được bởi UID ứng dụng, chỉ chủ sở hữu có quyền (`0400`/`0600`). Không thêm file đó vào image.
- Google Docs OAuth dạng Desktop hiện cần consent trên máy có trình duyệt; không hoàn tất được vòng consent localhost mới từ hosting. Việc cấp quyền Google và chuyển token hợp lệ cần cấu hình quản trị riêng. Xuất Word hoạt động độc lập.
- Cloud Run nguyên trạng không giữ được SQLite/MASTER qua vòng đời instance. Muốn dùng Google Cloud cần thiết kế lại lưu trữ bền vững hoặc dùng VM/disk phù hợp; chỉ mở link trong Chrome không yêu cầu Google Cloud.

## Kiểm tra đã thực hiện

Đã chạy sáu test launcher triển khai, gồm khởi động Streamlit thật trên cổng tạm, thiếu thông tin đăng nhập, sai cổng, workspace không hợp lệ và kiểm tra không in credential. Ruff đạt. `compose.yaml` và `render.yaml` đã qua kiểm tra cú pháp YAML và JSON Schema chính thức tương ứng.

Máy hiện tại chưa cài Docker, nên chưa chạy `docker build`, container Linux hay deploy Render thật. Cần kiểm tra vòng build, quyền disk, HTTPS/WebSocket, tìm kiếm từ mạng hosting và đăng nhập trên máy khác sau khi có tài khoản hosting. Các bước này không được coi là đã đạt từ kiểm thử Python cục bộ.
