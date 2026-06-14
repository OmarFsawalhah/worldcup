@echo off
REM Wipe all users, predictions, and scoring, then re-seed teams/players/matches
REM from data/*.json. USE BEFORE GOING LIVE so test data doesn't carry over.

cd /d "%~dp0"
echo.
echo This will DELETE all users, predictions, trivia answers, and points.
echo Teams, players, and the fixture list will be reloaded fresh from data/.
echo.
set /p CONFIRM="Type YES to confirm: "
if /i not "%CONFIRM%"=="YES" (
    echo Aborted.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

if exist worldcup.db del /q worldcup.db
if exist instance\worldcup.db del /q instance\worldcup.db

echo.
echo Seeding fresh database...
python scripts\seed.py

echo.
echo Done. All test data wiped, fresh seed loaded.
pause
