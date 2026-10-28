@echo off
cd /d "%~dp0"
echo Dashboard: http://localhost:8501
python -m uvicorn api:app --host 127.0.0.1 --port 8501
pause
