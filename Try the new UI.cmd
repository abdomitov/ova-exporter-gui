@echo off
rem Opens the redesigned window with a SIMULATED VMware server. No VMware, no OVF Tool,
rem no network and no files are needed or touched. Connect, pick a VM, queue it, cancel it.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools\preview_ui.py --try
) else (
    python tools\preview_ui.py --try
)
if errorlevel 1 (
    echo.
    echo Python 3.10 or newer with Tkinter is required.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
)
