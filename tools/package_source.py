"""Build a reviewable source ZIP from an allowlist; never package local installs."""
import hashlib
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from metadata import VERSION  # noqa: E402 - standalone script bootstraps src above

ROOT_FILES = (
    'launch.pyw', 'Start OVA Exporter.cmd', 'Start OVA Exporter.vbs',
    'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CONTRIBUTING.md',
    'SECURITY.md', '.gitignore', '.gitattributes', 'pyproject.toml', 'requirements-build.txt',
)
APP_FILES = tuple('src/'+name for name in (
    'app.py','branding.py','connection_settings.py','diagnostics.py','export_flow.py',
    'exporter.py','jobs.py','metadata.py','output_paths.py','project_paths.py','queue_view.py',
    'scrolling.py','secure_storage.py','settings_view.py','task_view.py','theme.py','tool_paths.py',
    'transfer_panel.py','ui_assets.py','vsphere.py','updates.py','update_ui.py',
))
TEST_FILES = tuple('tests/'+name for name in (
    'test_app.py','test_cancellation.py','test_connection_settings.py','test_jobs.py','test_ui.py','test_ui_performance.py','test_qa_regressions.py','test_updates.py','test_release_pipeline.py','test_security.py',
))
EXTRA_FILES = APP_FILES+TEST_FILES+(
    'tools/preview_ui.py','tools/benchmark_ui.py','tools/package_source.py','tools/offline_tests.py',
    'tools/make_icons.py','tools/runtime_licenses.py','tools/build_windows.ps1','tools/check_update_installer.py',
    'tools/ci_compiler.ps1','tools/ci_installer_check.py','tools/release_artifacts.py',
    'docs/ARCHITECTURE.md','docs/RELEASE_REVIEW.md','docs/UI_REVIEW.md','docs/QA_REVIEW.md','docs/SECURITY_REVIEW.md','docs/REPOSITORY_REVIEW.md','docs/WINDOWS_INSTALLER.md','docs/RELEASING.md','docs/DEVOPS_PATH.md',
    '.github/ISSUE_TEMPLATE/bug_report.md','.github/PULL_REQUEST_TEMPLATE.md',
    '.github/workflows/offline-tests.yml','.github/workflows/release-build.yml','.github/workflows/publish-release.yml',
    'assets/logo.svg','assets/logo.png','assets/app.ico',
    'packaging/windows.iss','packaging/installer-notes.txt','packaging/tool-requirement.txt',
)
OPTIONAL_IMAGES = tuple('docs/images/'+name+'.png' for name in (
    'exports-light', 'exports-dark', 'exports-minimum', 'connect', 'choose-vm', 'save-as',
    'settings', 'tool-missing'))


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
