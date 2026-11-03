# Kiểm tra kênh model AI Box

Kiểm tra lại: 2026-10-24. Tệp này không chứa khóa API.

## Kết quả mới nhất

- `GET /v1/models` trả HTTP 200, liệt kê `deepseek-v4.1-flash` và `deepseek-v4-pro-0813`.
- Yêu cầu kiểm tra sinh văn bản tối thiểu cho **cả hai model** vẫn trả HTTP 503, được nhận diện là thiếu kênh phục vụ model cho nhóm của khóa. Không có bài viết hoặc dữ liệu khách hàng được gửi.
- Mã yêu cầu Flash: `202610240613239989039318268d9d6GXGHkD9h`.
- Mã yêu cầu Pro: `202610240615166594966528268d9d6Wv7xrnLV`.
- Chưa xác nhận model nào sinh văn bản thành công. Model đã lưu của website được giữ nguyên.

Trong lần kiểm tra ngày 2026-10-23, phản hồi gốc đã nêu cụ thể nhóm:

```text
HTTP 503
error.code = model_not_found
Không có kênh khả dụng cho model deepseek-v4.1-flash
trong nhóm Vip (distributor)
```

Đây là lỗi model chưa có kênh phục vụ cho nhóm gán vào khóa. Việc đọc được `GET /v1/models` không bảo đảm model đó có kênh đang hoạt động. Đổi nội dung bài, tạo khóa mới cùng nhóm hoặc gửi lại liên tục không bảo đảm xử lý được việc gán kênh.

## Cách xử lý tại tài khoản AI Box

1. Đăng nhập tài khoản AI Box và mở **API Keys**. Có thể bắt đầu từ [trang quản lý khóa](https://home.ai-box.vn/console/token).
2. Kiểm tra nhóm gán cho khóa, quyền/giới hạn model và model nào được nhà cung cấp xác nhận có kênh hoạt động. Website hiện dùng `deepseek-v4.1-flash`; không đổi sang tên model chỉ vì thấy trong tài liệu marketing.
3. Nếu có quyền chỉnh khóa, chọn nhóm/model được cấp phép và có kênh hoạt động. Nếu chỉ có nhóm `Vip (distributor)` hoặc không sửa được nhóm, cần chủ tài khoản/AI Box mở kênh đúng cho nhóm này.
4. Nếu được cấp khóa hoặc model mới, nhập tại bản local trên Mac: **Soạn & duyệt → Kết nối AI Box → Lưu kết nối AI**. Không gửi khóa qua chat.
5. Bấm **Kiểm tra kết nối AI**. Chỉ khi kiểm tra sinh văn bản thành công mới coi kết nối đã hoạt động. Trên link chia sẻ, bấm **Đọc lại cấu hình AI** sau khi cấu hình trên Mac.

## Nội dung có thể gửi bộ phận hỗ trợ AI Box

```text
Ngày 24/10/2026, mình kiểm tra API Box cho website biên tập nội dung.
Endpoint: POST https://api.ai-box.vn/v1/chat/completions
Model deepseek-v4.1-flash và deepseek-v4-pro-0813 đều trả HTTP 503,
lỗi thiếu kênh phục vụ model cho nhóm của khóa.
GET /v1/models vẫn trả 200 và liệt kê đúng hai model trên.
Phản hồi ngày 23/10 đã nêu nhóm Vip (distributor), error.code=model_not_found.

Nhờ kiểm tra kênh/model đang mở cho nhóm của khóa,
hoặc hướng dẫn chuyển khóa sang nhóm được phép có kênh hoạt động.

Mã yêu cầu Flash mới nhất: 202610240613239989039318268d9d6GXGHkD9h
Mã yêu cầu Pro mới nhất: 202610240615166594966528268d9d6Wv7xrnLV
Mình không gửi khóa API trong nội dung này.
```

Đây là nội dung chuẩn bị để người dùng gửi khi cần; ứng dụng chưa gửi tin nhắn hoặc thay đổi tài khoản AI Box. Soạn thủ công, lưu bản thảo, đối chiếu và phê duyệt vẫn hoạt động. Cấu hình/quota ChatGPT và Codex không bị thay đổi.
