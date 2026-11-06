# Windows installer

End users download `OVA-Exporter-GUI-2.3.0-Windows-x64-Setup.exe`, run it,
accept the app license and choose the install folder. Python and Tk are included.
Installation is per Windows user and does not need administrator rights by default.
Start menu and optional Desktop shortcuts use the project icon. Uninstall keeps
saved hints and exported VMs; remove saved hints through the app if desired.

VMware OVF Tool remains a separate required installation under Broadcom's license.
The completion page offers its official download link. A standard installation is
detected automatically. The setup does not download or redistribute VMware files.
The installer explains this requirement before installation and again at the end.
On startup the app shows a red status and blocks new exports when the executable
is missing. Use Locate OVF Tool for custom folders or Auto-detect after installation.
The custom executable location is encrypted and remembered; no environment variable
or restart is required. A file-presence check is not a full compatibility test.

This installer is unsigned. Windows may display an unknown-publisher/SmartScreen
warning. Code signing and clean Windows 10/11 installation/uninstallation tests
remain release tasks; do not advertise this build as certified or warning-free.

Version 2.3.0 includes update notifications and user-confirmed installer downloads.
Use the Updates menu for a manual check or to disable automatic startup checks.
Users can defer the prompt for a day or skip that version. Installation is blocked
until queued/active tasks finish and export setup windows are closed. Downloads
are restricted to the project's GitHub release assets over HTTPS, with size and
SHA-256 verification (repeated before launching setup). Installers remain unsigned;
this does not establish publisher identity or protect against a compromised release
account. The updater never downloads VMware OVF Tool or restarts host services.
Users on older app versions must install 2.3.0 manually to obtain the updater.

## Build

Use a Windows x64 Python installation with Tkinter. Install the official Inno
Setup compiler, then in a build environment:

```powershell
py -3 -m pip install -r requirements-build.txt
py -3 tools/offline_tests.py
py -3 tools/preview_ui.py --check
.\tools\build_windows.ps1 -Python python -Iscc 'C:\Path\To\ISCC.exe'
```

The build collects licenses for the exact Python/Tcl/Tk/OpenSSL runtime from the
installed runtime and their upstream projects. Network access to those upstream
license URLs is required. Only build tooling uses Pillow; the app does not.

The result and its SHA-256 sidecar are in `dist/`. Neither is committed to Git;
attach them to a GitHub Release. The compiler copies the application's onedir
bundle, app license and dependency notices into the installer. It never closes
active exports automatically during upgrade.

For an isolated check of the bundled app without credentials/settings/network:

```powershell
.\dist\OVAExporterGUI\OVAExporterGUI.exe --self-test-report "$PWD\check.json"
```

The GUI executable writes a small JSON report on completion and exits. This
checks the frozen payload; it does not validate real VMware export or prove a
successful clean-machine install/uninstall.
