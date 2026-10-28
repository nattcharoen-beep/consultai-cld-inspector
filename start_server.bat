@echo off
chcp 65001 > nul
echo ========================================================
echo   ConsultAI: CLD & Position Code Inspector Server
echo ========================================================
echo.
cd /d "%~dp0"
python server.py
pause
