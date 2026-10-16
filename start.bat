@echo off
REM Start the dashboard. Run setup.bat first (only needed once).
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo No venv yet. Run setup.bat first.
    exit /b 1
)
call venv\Scripts\activate.bat
streamlit run app/main.py
