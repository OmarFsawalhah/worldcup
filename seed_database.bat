@echo off
REM Double-click to load teams, players, matches, and admin accounts.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

echo Seeding database...
python scripts\seed.py

echo.
pause
