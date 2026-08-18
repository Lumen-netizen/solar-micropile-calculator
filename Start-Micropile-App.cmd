@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto missing
start "" ".venv\Scripts\pythonw.exe" "app.py"
exit /b 0

:missing
echo Project-local Python 3.12 runtime was not found.
echo Please check the .venv folder.
pause
exit /b 1
