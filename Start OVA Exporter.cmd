@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 launch.pyw
) else (
    python launch.pyw
)
if errorlevel 1 (
    echo.
    echo Python 3.10 or newer with Tkinter is required.
    echo Install Python from python.org and enable its launcher or PATH option.
    pause
)
