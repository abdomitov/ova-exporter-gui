"""Operating-system differences in one place.

Only macOS is special-cased. Every other platform keeps the original Windows
behavior, so Windows builds and the existing tests are unaffected.
"""
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def is_mac():
    return sys.platform == 'darwin'


def tool_name():
    """File name of the OVF Tool executable on this platform."""
    return 'ovftool' if is_mac() else 'ovftool.exe'


def platform_label():
    return 'macOS' if is_mac() else 'Windows'


def settings_directory():
    if is_mac():
        return Path.home() / 'Library' / 'Application Support' / 'OVA Exporter'
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    return local / 'OVA Exporter'


def tool_candidates(base):
    """Usual OVF Tool locations, most specific first. Nothing here is executed."""
    name = tool_name()
    candidates = [Path(base) / 'ovftool' / name]
    if is_mac():
        home = Path.home()
        candidates += [Path('/Applications/VMware OVF Tool') / name,
                       Path('/Applications/ovftool') / name,
                       home / 'Applications' / 'VMware OVF Tool' / name,
                       home / 'ovftool' / name,
                       Path('/usr/local/bin') / name,
                       Path('/opt/local/bin') / name]
    else:
        for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / 'VMware' / 'VMware OVF Tool' / name)
    on_path = shutil.which(name)
    if on_path:
        candidates.append(Path(on_path))
    return candidates


def open_folder(folder):
    """Show a folder in Explorer or Finder."""
    folder = str(folder)
    if is_mac():
        subprocess.run(['/usr/bin/open', '--', folder], check=True, timeout=10)  # nosec B603
    elif hasattr(os, 'startfile'):
        os.startfile(folder)  # nosec B606 - opens the user's own destination folder
    else:
        webbrowser.open(Path(folder).resolve().as_uri())


def installer_filename(version):
    """The release asset this platform's updater looks for."""
    if is_mac():
        return f'OVA-Exporter-GUI-{version}-macOS-Intel.dmg'
    return f'OVA-Exporter-GUI-{version}-Windows-x64-Setup.exe'


def shortcut_modifiers():
    """Control everywhere; Command too on a Mac."""
    return ('Control', 'Command') if is_mac() else ('Control',)
