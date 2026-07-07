@echo off
echo Installing A2A Task Watcher extension...
set TARGET=%USERPROFILE%\.vscode\extensions\a2a-task-watcher
if not exist "%TARGET%" mkdir "%TARGET%"
copy /Y "%~dp0package.json" "%TARGET%\package.json"
copy /Y "%~dp0extension.js" "%TARGET%\extension.js"
echo Done. Reload VSCode (Ctrl+Shift+P -> Reload Window) to activate.
pause
