"""Private local AI setup: hidden input, atomic configuration, optional API probe."""

from __future__ import annotations

import argparse
import getpass
import sys
import warnings

from ai_client import AIServiceError, check_ai_connection
from settings import get_ai_settings, save_ai_settings


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Kết nối AI Box riêng cho website FRIC LAW; không nhận khóa trong đối số.'
    )
    parser.add_argument(
        '--check-only', action='store_true', help='Kiểm tra cấu hình hiện có, không thay khóa.'
    )
    parser.add_argument(
        '--no-test', action='store_true', help='Chỉ lưu; chưa gửi yêu cầu kiểm tra có phí tới AI Box.'
    )
    args = parser.parse_args(argv)
    try:
        config = get_ai_settings()
        if not args.check_only:
            if not sys.stdin.isatty():
                print(
                    'Chạy trực tiếp trong Terminal để nhập khóa ẩn, hoặc dùng ô mật khẩu trong ứng dụng.',
                    file=sys.stderr,
                )
                return 1
            print(
                'Nhập API key từ tài khoản AI Box; chỉ website dùng khóa này, không đổi cấu hình Codex/ChatGPT.'
            )
            print('Endpoint cố định: ' + config['base_url'] + ' · Chat Completions. Không gửi khóa qua chat.')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                key = getpass.getpass('AI Box API key (nhập ẩn; để trống để giữ khóa đang có): ').strip()
            if not key and not config['configured']:
                print('Chưa có khóa AI Box. Chưa lưu hoặc kết nối AI.', file=sys.stderr)
                return 1
            model = input(f'Model [{config["model"]}]: ').strip() or config['model']
            if key.startswith('AIza'):
                config = save_ai_settings(gemini_key=key, model=model, provider='gemini')
            else:
                config = save_ai_settings(aibox_key=key or None, model=model)
            print(
                'Đã lưu cấu hình riêng trên máy. Bấm Làm mới cấu hình AI trong ứng dụng; không cần restart.'
            )
        if args.no_test:
            print('Chưa kiểm tra API; lưu khóa không đồng nghĩa kết nối thành công.')
            return 0
        print('Đang kiểm tra bằng một yêu cầu nhỏ tới AI Box; có thể phát sinh phí theo tài khoản AI Box.')
        result = check_ai_connection(model=config['model'])
        print('AI Box đã phản hồi thành công. Model: ' + result['model'])
        return 0
    except AIServiceError as exc:
        print(str(exc), file=sys.stderr)
        if exc.status_code is not None:
            print(f'HTTP {exc.status_code} · {exc.code}', file=sys.stderr)
        if exc.request_id:
            print('Mã yêu cầu AI Box: ' + exc.request_id, file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print('Đã hủy nhập khóa hoặc Terminal không hỗ trợ nhập ẩn. Chưa lưu cấu hình mới.', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(
            'Không lưu/đọc được cấu hình AI. Kiểm tra quyền thư mục và tên model; không in chi tiết chứa khóa.',
            file=sys.stderr,
        )
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
