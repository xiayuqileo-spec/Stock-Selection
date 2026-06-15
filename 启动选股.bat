@echo off
cd /d "%~dp0"
title 选股
if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" app.py
) else (
  python app.py
)
pause
