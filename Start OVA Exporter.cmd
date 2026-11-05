@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 app.py
) else (
    python app.py
)
if errorlevel 1 (
    echo.
    echo Python 3.10 or newer with Tkinter is required.
    echo Install Python from python.org and enable its launcher or PATH option.
    pause
)
