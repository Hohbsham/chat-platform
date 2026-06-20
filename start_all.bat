@echo off
cd /d d:\ClothesNetData\chat-platform
echo Starting A2A Chat Platform v2...

REM Start server in background
start "ChatServer" /B C:\Users\YANGZ\AppData\Local\Programs\Python\Python311\python.exe server.py --port 8765

REM Wait for server
timeout /t 4 /nobreak >nul

REM Start agents
start "Claude" /B C:\Users\YANGZ\AppData\Local\Programs\Python\Python311\python.exe -B agent.py auto --name Claude --role "Senior Code Reviewer" --goal "Find bugs and improve code" --backstory "15 years experience" --capabilities code_review,file_edit,shell_exec --auto-reply --verbose --poll-interval 5
start "Cursor" /B C:\Users\YANGZ\AppData\Local\Programs\Python\Python311\python.exe -B agent.py auto --name Cursor --role "Full-Stack Developer" --goal "Generate and debug code" --backstory "Expert in modern frameworks" --capabilities code_generation,debugging,refactoring --auto-reply --verbose --poll-interval 5
start "OpenClaw" /B C:\Users\YANGZ\AppData\Local\Programs\Python\Python311\python.exe -B agent.py auto --name OpenClaw --role "AI Gateway Orchestrator" --goal "Route and monitor tasks" --backstory "Central hub for agent network" --capabilities chat,notification,task_orchestration,file_watch --auto-reply --verbose --poll-interval 5

echo All services started!
echo   HTTP:  http://localhost:8765
echo   WS:    ws://localhost:8766
