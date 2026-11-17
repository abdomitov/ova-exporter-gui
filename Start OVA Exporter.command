#!/bin/bash
# Run OVA Exporter GUI from source on macOS. Needs Python 3.10+ with Tkinter
# (python.org installer, or MacPorts: sudo port install python312 py312-tkinter).
cd "$(dirname "$0")"
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import tkinter' 2>/dev/null; then
        exec "$candidate" launch.pyw "$@"
    fi
done
echo "Python 3.10 or newer with Tkinter was not found."
echo "Install it from https://www.python.org/downloads/macos/ or with MacPorts:"
echo "  sudo port install python312 py312-tkinter"
read -r -p "Press Return to close." _
