"""Find a user-installed OVF Tool without redistributing VMware binaries."""
import os
import shutil
from pathlib import Path


def find_ovftool(base):
    """Prefer an explicit executable, then a private copy, installation, or PATH."""
    configured = os.environ.get('OVFTOOL_PATH', '').strip().strip('"')
    if configured:
        return Path(configured)  # An explicit override must not select another binary.
    candidates = []
    candidates.append(Path(base) / 'ovftool' / 'ovftool.exe')
    for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / 'VMware' / 'VMware OVF Tool' / 'ovftool.exe')
    on_path = shutil.which('ovftool.exe')
    if on_path:
        candidates.append(Path(on_path))
    return next((path for path in candidates if path.is_file()), None)
