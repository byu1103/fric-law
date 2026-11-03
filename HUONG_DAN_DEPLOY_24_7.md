# Đưa FRIC LAW Content Studio lên hosting

Đích đến là một URL HTTPS mở được bằng Chrome trên các máy khác, có đăng nhập, hoạt động khi Mac tắt. Bản này dùng Render với ổ đĩa lưu SQLite và MASTER Word. Chưa có tài khoản hoặc dịch vụ cloud nào được tạo; chưa có URL Render thực tế.

Link `trycloudflare.com` chỉ dùng thử, phụ thuộc tiến trình tunnel và máy Mac. Tạo hosting là bước riêng; lỗi AI Box thiếu kênh model cũng cần xử lý riêng.

## 1. Chuẩn bị tài khoản và mã nguồn sạch

- Tạo tài khoản tại [GitHub](https://github.com/) và [Render](https://dashboard.render.com/). Tự đăng nhập và nhập thông tin thanh toán trên trang chính thức khi được yêu cầu.
- Cài [GitHub Desktop](https://desktop.github.com/), rồi đăng nhập tài khoản GitHub của bạn.
- Dùng thư mục mã nguồn sạch `~/Documents/FRIC_LAW_Deploy_Source` đã được chuẩn bị cho lần triển khai này. Không tải toàn bộ thư mục dự án đang chạy lên GitHub.

Chỉ đưa mã nguồn lên repository. Không thêm `.env`, `.runtime`, `.venv`, cơ sở dữ liệu, MASTER Word, hồ sơ khách hàng hay token OAuth. Bản trên cloud bắt đầu với workspace trống; dữ liệu hiện tại trên Mac vẫn ở Mac.

## 2. Đưa mã nguồn vào repository riêng tư

1. Mở [trang tạo repository](https://github.com/new). Đặt tên `fric-law-content-studio`, chọn **Private**, rồi tạo repository. Có thể để repository trống.
2. Trong GitHub Desktop, chọn **File → Clone Repository**, chọn repository vừa tạo. Đặt đường dẫn local là `~/Documents/GitHub/fric-law-content-studio`.
3. Chép **nội dung bên trong** `FRIC_LAW_Deploy_Source` vào thư mục repository vừa clone. Để tránh bỏ sót tệp ẩn, mở Terminal và chạy:

   ```bash
   cp -R "$HOME/Documents/FRIC_LAW_Deploy_Source/." "$HOME/Documents/GitHub/fric-law-content-studio/"
   ```

   Chỉ dùng lệnh này khi đã clone vào đúng đường dẫn trên. Nếu bạn chọn vị trí khác trong GitHub Desktop, thay đường dẫn đích bằng vị trí đó.

4. Kiểm tra trong GitHub Desktop: các tệp `render.yaml`, `Dockerfile`, `.dockerignore`, `app.py`, `requirements.txt` phải nằm ngay ở gốc repository; thư mục `deploy` chứa `entrypoint.py`. Không để chúng bị lồng trong `FRIC_LAW_Deploy_Source/`.
5. Ghi commit message `Prepare FRIC LAW hosting`, bấm **Commit to main**, rồi **Push origin**. Kiểm tra trên GitHub rằng repository vẫn là **Private**.

Nếu tải bằng giao diện web thay cho GitHub Desktop, phải tải **nội dung** thư mục sạch và cả tệp ẩn `.dockerignore`, không chỉ kéo nguyên thư mục cha. Trong Finder, nhấn **Command + Shift + .** để hiện tệp ẩn. GitHub hướng dẫn [tạo repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository), [clone bằng Desktop](https://docs.github.com/en/desktop/adding-and-cloning-repositories/cloning-and-forking-repositories-from-github-desktop) và [tải tệp](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).

## 3. Tạo mật khẩu đăng nhập mà không in mật khẩu hoặc hash

Chạy trong Terminal trên Mac, dùng **dự án gốc** có môi trường Python đã cài:

```bash
cd "/Users/macbook1/Documents/Job/Fric Law/FRIC_LAW_Content_Studio"
umask 077
mkdir -p .runtime
.venv/bin/python -m access_control hash > .runtime/deploy-access.hash
chmod 600 .runtime/deploy-access.hash
```

Nhập mật khẩu mới ít nhất 12 ký tự và nhập lại khi được hỏi. Ký tự sẽ không hiện khi gõ. Chỉ tiếp tục khi lệnh kết thúc thành công, không báo lỗi xác nhận mật khẩu. Lưu mật khẩu trong trình quản lý mật khẩu để đăng nhập sau này.

Khi đã tới ô `FRIC_ACCESS_PASSWORD_HASH` của Render ở bước tiếp theo, chạy:

```bash
pbcopy < .runtime/deploy-access.hash
```

Dán trực tiếp vào ô bí mật của Render. Không dán hash hoặc mật khẩu vào chat, GitHub, `render.yaml` hay log. Tên đăng nhập mặc định là `editor`; mật khẩu đăng nhập là mật khẩu bạn vừa chọn, không phải chuỗi hash.

## 4. Tạo dịch vụ Render bằng Blueprint

1. Trong Render Dashboard, chọn **New → Blueprint**, kết nối GitHub và cấp quyền cho repository riêng tư vừa tạo.
2. Chọn repository, nhánh `main`, Blueprint path `render.yaml`. Render mặc định đọc tệp này tại gốc repository. Xem [hướng dẫn Blueprint chính thức](https://render.com/docs/infrastructure-as-code).
3. Kiểm tra tài nguyên trước khi xác nhận:

   | Thiết lập đã có trong mã | Giá trị |
   | --- | --- |
   | Service | Docker web service |
   | Region | Singapore |
   | Plan | `0.5c-512mb` |
   | Số instance | `1` |
   | Persistent disk | `fric-editorial-data`, 1 GB, mount `/data` |
   | Workspace | `FRIC_WORKSPACE=/data` |
   | Đăng nhập bắt buộc | `FRIC_AUTH_REQUIRED=1`, `FRIC_HOSTED=1` |

4. Điền `FRIC_ACCESS_PASSWORD_HASH` bằng clipboard từ bước 3. Không thay bằng mật khẩu rõ. Chưa cần API key để mở ứng dụng và thử tìm kiếm công khai.
5. Đây là **hosting và disk có phí**. Đọc tổng chi phí được Render hiển thị và [bảng giá hiện hành](https://render.com/pricing) trước khi bấm **Deploy Blueprint**. Không chọn gói Free thay cho cấu hình có disk.
6. Chờ trạng thái **Live**, rồi sao chép URL HTTPS thực tế Render hiển thị ở trang service. Mở URL đó trên Chrome và đăng nhập. Không dùng lại URL `trycloudflare.com`, không đoán trước tên miền Render.

Disk giữ dữ liệu được ghi dưới `/data` qua restart/deploy. Cấu hình này dùng một instance; khi redeploy có thể có thời gian gián đoạn. Hosting không có nghĩa là được bảo đảm truy cập liên tục trong mọi tình huống. Xem [giới hạn persistent disk](https://render.com/docs/disks).

## 5. Kiểm tra trước khi dùng cho công việc

1. Mở URL bằng cửa sổ ẩn danh: phải thấy màn hình đăng nhập trước khi thấy studio.
2. Đăng nhập bằng `editor` và mật khẩu đã tạo. Thử tìm kiếm nguồn, viết một bản nháp thử và lưu; không duyệt hoặc xuất nội dung chưa kiểm tra.
3. Restart service từ Render Dashboard, đăng nhập lại và xác nhận bản nháp thử còn tồn tại. Bước này kiểm tra việc gắn disk thực tế.
4. Mở cùng URL trên điện thoại hoặc máy khác. Sau đó tắt Mac và kiểm tra lại: dịch vụ Render phải hoạt động độc lập với Mac.

Nếu cần AI soạn thảo, vào **service → Environment** của Render, thêm `AIBOX_API_KEY` bằng khóa AI Box của bạn; `AIBOX_MODEL` đã có mặc định `deepseek-v4.1-flash`. Lưu và áp dụng thay đổi, rồi vào **Soạn & duyệt → Kiểm tra kết nối AI**. Không nhập khóa qua giao diện biên tập bản cloud. Khóa hiện gặp lỗi nhóm/model thiếu kênh sẽ vẫn gặp lỗi trên hosting; xem [hướng dẫn AI Box](AI_BOX_KIEM_TRA_KENH.md). Website chỉ gọi AI Box; cấu hình này không thay cài đặt hoặc quota của cuộc chat Codex.

## 6. Sau khi đã chạy được

- **Dữ liệu cũ:** việc chuyển SQLite/MASTER và tài liệu tham chiếu từ Mac là bước di chuyển dữ liệu riêng. Cần sao lưu, dừng ghi và kiểm tra dữ liệu sau chuyển; không đưa dữ liệu đó vào GitHub.
- **Cập nhật mã:** push bản cập nhật vào repository, rồi deploy thủ công trên Render. Service đã tắt auto-deploy mã; nếu muốn kiểm soát cả thay đổi Blueprint, đặt **Blueprint Settings → Auto Sync → No**, sau đó chủ động Manual Sync.
- **Sao lưu:** cần bản sao độc lập của workspace, dùng SQLite backup API hoặc dừng ứng dụng trước khi sao chép DB. Disk bền vững không thay thế việc sao lưu.
- **Google Docs:** OAuth cần cấu hình quản trị riêng trên hosting. Xuất Word có thể dùng độc lập. Không đưa token Google vào repository.

## Khi chưa mở được

| Triệu chứng | Việc cần kiểm tra |
| --- | --- |
| Không thấy `render.yaml` hoặc Dockerfile | Các tệp phải ở gốc repository, không bị lồng thêm thư mục. |
| Build báo thiếu tệp | Kiểm tra thư mục `deploy/entrypoint.py`, `requirements.txt` và `.dockerignore` đã được push. |
| Service không lên Live | Xem Render Logs. Chỉ chia sẻ đoạn lỗi đã bỏ khóa, mật khẩu và dữ liệu khách hàng. |
| Báo chưa cấu hình đăng nhập | Kiểm tra biến `FRIC_ACCESS_PASSWORD_HASH` chứa đầy đủ hash đã tạo; không có dấu ngoặc thêm ngoài giá trị. |
| Lưu bài lỗi hoặc mất bài sau restart | Kiểm tra disk `/data`, `FRIC_WORKSPACE=/data` và quyền ghi; giữ một instance. |
| AI Box trả `model_not_found`/thiếu kênh | Cần AI Box mở kênh cho nhóm/model hoặc khóa hợp lệ khác; deploy không tự sửa quyền API. |

Đến thời điểm soạn hướng dẫn này, chưa chạy build Docker hoặc deploy Render thật trên tài khoản của bạn. Kết quả Live, quyền disk, WebSocket, mạng tìm kiếm và đăng nhập trên máy khác cần được kiểm tra sau khi tạo dịch vụ.
