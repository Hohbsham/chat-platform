@echo off
:loop
echo BPTtrain starting at %time%
python d:\ClothesNetData\chat-platformpt_agent.py auto --name BPTtrain
echo BPTtrain stopped at %time%. Restarting in 5s...
timeout /t 5 >/dev/null
goto loop
