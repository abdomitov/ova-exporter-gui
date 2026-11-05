"""Build a reviewable source ZIP from an allowlist; never package local installs."""
import hashlib
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metadata import VERSION

ROOT_FILES = (
    'app.py', 'wizard.py', 'dashboard.py', 'task_view.py', 'transfer_ui.py', 'branding.py',
    'theme.py', 'ui_assets.py', 'accordion.py', 'jobs.py', 'exporter.py',
    'vsphere.py', 'diagnostics.py', 'connection_settings.py', 'secure_storage.py', 'tool_paths.py', 'output_paths.py',
    'metadata.py', 'launch.pyw', 'Start OVA Exporter.cmd', 'Start OVA Exporter.vbs',
    'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'CONTRIBUTING.md', 'SECURITY.md', '.gitignore', '.gitattributes', 'pyproject.toml',
    'test_app.py', 'test_cancellation.py', 'test_connection_settings.py',
    'test_jobs.py', 'test_ui.py', 'requirements-build.txt',
)
EXTRA_FILES = (
    'tools/preview_ui.py', 'tools/package_source.py', 'tools/offline_tests.py',
    'docs/ARCHITECTURE.md', 'docs/PUBLISHING.md', 'docs/VALIDATION.md',
    '.github/ISSUE_TEMPLATE/bug_report.md', '.github/PULL_REQUEST_TEMPLATE.md',
    '.github/workflows/offline-tests.yml', 'docs/REVIEW_PLAN.md', 'docs/RELEASE_REVIEW.md',
    'tools/make_icons.py', 'tools/runtime_licenses.py', 'tools/build_windows.ps1', 'tools/publish_github.ps1',
    'assets/logo.svg', 'assets/logo.png', 'assets/app.ico',
    'packaging/windows.iss', 'packaging/installer-notes.txt', 'docs/WINDOWS_INSTALLER.md',
)
OPTIONAL_IMAGES = ('docs/images/dashboard-dark.jpg', 'docs/images/dashboard-light.jpg',
                   'docs/images/dashboard-compact.jpg', 'docs/images/new-export-dark.jpg',
                   'docs/images/vm-selection-dark.jpg')


def build():
    output_dir = ROOT / 'dist'
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f'ova-exporter-gui-{VERSION}-source.zip'
    files = list(ROOT_FILES + EXTRA_FILES)
    files.extend(name for name in OPTIONAL_IMAGES if (ROOT / name).is_file())
    missing = [name for name in files if not (ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError('Missing release sources: ' + ', '.join(missing))
    prefix = f'ova-exporter-gui-{VERSION}/'
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT / name, prefix + name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_suffix('.zip.sha256')
    checksum.write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(f'{output}\n{len(files)} source files; no runtime, cache, exports or history\nSHA-256: {digest}')
    return output


if __name__ == '__main__':
    build()
