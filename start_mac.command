#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
if ! python -c 'import streamlit, docx, requests, bs4, dotenv' >/dev/null 2>&1; then
  python -m pip install --index-url https://pypi.org/simple -r requirements.txt
fi
if [ ! -e .env ]; then cp .env.example .env; fi
if ! python run_local.py start --open-browser; then
  echo 'Khởi động thất bại. Xem chi tiết ở trên hoặc tệp .runtime/server.log.'
  if [ -t 0 ]; then read -r -p 'Nhấn Enter để đóng cửa sổ…'; fi
  exit 1
fi
