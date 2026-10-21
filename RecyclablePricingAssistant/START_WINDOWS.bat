@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Could not create the virtual environment. Make sure Python 3.12 or 3.13 is installed.
        pause
        exit /b 1
    )
)

echo Installing or updating project dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo Launching Recyclable Pricing Assistant...
".venv\Scripts\python.exe" run.py
pause
