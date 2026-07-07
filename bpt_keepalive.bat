@echo off
cd /d d:\ClothesNetData\chat-platform
:loop
python bpt_keepalive.py
echo BPTtrain restarted at %time%
timeout /t 3 >nul
goto loop
