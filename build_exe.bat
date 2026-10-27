@echo off
setlocal
cd /d "%~dp0"

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b %errorlevel%

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name B0Pulse ^
  --distpath release ^
  --icon assets\b0pulse.ico ^
  --add-data "web;web" ^
  --add-data "assets;assets" ^
  --collect-all uvicorn ^
  launcher.py

if errorlevel 1 exit /b %errorlevel%
echo.
echo Build completed: %~dp0release\B0Pulse.exe
endlocal
