$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv')) { py -m venv .venv }
& '.\.venv\Scripts\python.exe' -c 'import streamlit, docx, requests, bs4, dotenv'
if ($LASTEXITCODE -ne 0) {
  & '.\.venv\Scripts\python.exe' -m pip install --index-url https://pypi.org/simple -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
& '.\.venv\Scripts\python.exe' run_local.py start --open-browser
