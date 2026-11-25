@echo off
REM 启动 A2A 平台（含联邦接入）。已经在跑就不重复启动。
cd /d D:\ClothesNetData\chat-platform
python -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',8765))==0 else 1)"
if %errorlevel%==0 (
  echo [A2A] 已经在跑：http://127.0.0.1:8765
) else (
  echo [A2A] 启动中…
  start "" /B python server.py --port 8765
  timeout /t 5 /nobreak >nul
)
echo.
echo   本机平台 : http://127.0.0.1:8765
echo   给别人   : http://本机Tailscale地址:8765
echo   邀请码   : federation_invite.txt 里那一行
echo.
