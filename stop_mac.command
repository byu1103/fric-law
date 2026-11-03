#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  .venv/bin/python run_local.py stop
else
  echo 'Không tìm thấy môi trường .venv của ứng dụng.'
  exit 1
fi
