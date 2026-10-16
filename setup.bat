@echo off
REM One-time setup (safe to run again): creates the venv and installs everything.
cd /d "%~dp0"
if not exist venv (
    python -m venv venv || goto :fail
)
call venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
pip install -r requirements.txt || goto :fail
if not exist .env copy .env.example .env >nul
echo.
echo Setup finished. Check it with:  venv\Scripts\python check_setup.py --full
echo Then start the app with:        start.bat
exit /b 0
:fail
echo.
echo Setup failed. Read the message above, fix it, and run setup.bat again.
exit /b 1
