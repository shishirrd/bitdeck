@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --require-hashes -r requirements-lock.txt
if errorlevel 1 exit /b 1
echo Ready. Run launch.cmd to open BitDeck.
