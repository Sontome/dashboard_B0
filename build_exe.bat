@echo off
cd /d "%~dp0"
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name B0Pulse_v4 --icon "assets\b0pulse.ico" --add-data "web;web" --add-data "assets;assets" launcher.py
xcopy /E /I /Y "data" "dist\data" >nul
echo.
echo Da tao: dist\B0Pulse_v4.exe
pause
