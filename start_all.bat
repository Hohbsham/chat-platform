@echo off
cd /d d:\ClothesNetData\chat-platform
echo ==========================================
echo   A2A Platform v3 — OS-Level Wake-Up
echo ==========================================

echo [1/3] A2A Server :8765...
start "A2A-Server" /MIN python server.py --port 8765
timeout /t 3 /nobreak >nul

echo [2/3] Webhook Hub :8767...
start "Webhook-Hub" /MIN python webhook_hub.py
timeout /t 2 /nobreak >nul

echo [3/3] Desktop Watcher...
start "Desktop-Watcher" powershell -NoExit -File watcher.ps1

echo.
echo   A2A:  http://localhost:8765
echo   Hub:  http://localhost:8767/health
echo.
echo All services started. Close this window.
pause
