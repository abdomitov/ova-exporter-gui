#!/bin/bash
# Opens the redesigned window against a SIMULATED VMware server. No VMware, OVF Tool,
# network or files are needed or touched.
cd "$(dirname "$0")"
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import tkinter' 2>/dev/null; then
        exec "$candidate" tools/preview_ui.py --try
    fi
done
echo "Python 3.10 or newer with Tkinter was not found (python.org, or MacPorts: sudo port install python312 py312-tkinter)."
read -r -p "Press Return to close." _
