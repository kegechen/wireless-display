@echo off
echo === Wireless Display Server Setup (Windows) ===
echo.
echo Installing Python dependencies...
pip install mss Pillow
echo.
echo Done! Start server with:
echo   python server/main.py --list-monitors
echo   python server/main.py --monitor 1
echo.
pause
