"""Find a user-installed OVF Tool without redistributing VMware binaries."""
import os
import shutil
import base64
import json
import tempfile
from pathlib import Path
from secure_storage import WindowsDataProtection


def tool_file_exists(path):
    try:
        return bool(path and Path(path).is_file())
    except (OSError,ValueError):
        return False


def find_ovftool(base, selected=None):
    """Prefer an explicit executable, then a private copy, installation, or PATH."""
    if selected:
        return Path(selected)
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
    return next((path for path in candidates if tool_file_exists(path)), None)


class ToolLocation:
    """A custom local executable path; encrypted separately from connection data."""
    def __init__(self,directory,protector=None):
        self.path=Path(directory)/'tool_location.json'
        self.protector=protector if protector is not None else WindowsDataProtection()

    def read(self):
        try:
            if self.path.stat().st_size>100_000:
                raise ValueError('Saved tool location is too large.')
            data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        if not isinstance(data,dict) or set(data)!={'version','payload'} or data['version']!=1:
            raise ValueError('Invalid saved tool location.')
        value=self.protector.unprotect(base64.b64decode(data['payload'],validate=True),'ovftool-path').decode('utf-8')
        if not value or len(value)>32768 or '\0' in value:
            raise ValueError('Invalid saved tool path.')
        return Path(value)

    def save(self,value):
        if value is None:
            self.path.unlink(missing_ok=True)
            return
        plaintext=str(value).encode('utf-8')
        ciphertext=self.protector.protect(plaintext,'ovftool-path')
        if self.protector.unprotect(ciphertext,'ovftool-path')!=plaintext:
            raise OSError('Tool location encryption verification failed.')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.path.parent,delete=False) as stream:
                temporary=Path(stream.name)
                json.dump({'version':1,'payload':base64.b64encode(ciphertext).decode('ascii')},stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
