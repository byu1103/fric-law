#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print 'Chưa có Python của dự án. Xem hướng dẫn cài đặt trong README.md.'
  read -r '?Nhấn Enter để đóng.'
  exit 1
fi
if .venv/bin/python setup_ai.py; then
  print 'Mở lại Soạn & duyệt → Kết nối AI Box và bấm kiểm tra kết nối.'
else
  print 'AI chưa kết nối thành công. Đọc thông báo phía trên; không gửi khóa qua chat.'
fi
read -r '?Nhấn Enter để đóng.'
