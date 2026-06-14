@echo off
REM Double-click to start the World Cup predictor locally.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt

echo.
echo Starting server at http://localhost:5000
echo Press Ctrl+C to stop.
echo.
set FLASK_APP=app.py
python app.py

pause
