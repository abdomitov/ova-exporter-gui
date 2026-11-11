"""Real installer checks restricted to a fresh GitHub-hosted Windows runner.

Never run installation tests on a developer PC or a self-hosted production runner.
The test uses a pinned public baseline installer, a disposable installation folder,
no credentials, and no VMware connection. Windows protections remain enabled.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from metadata import VERSION  # noqa: E402 - standalone script bootstraps src above

BASELINE_URL = ('https://github.com/abdomitov/ova-exporter-gui/releases/download/v2.3.1/'
                'OVA-Exporter-GUI-2.3.1-Windows-x64-Setup.exe')
BASELINE_HASH = 'cf06f4dca0ed8dc5d9b050298a4426bfff8fe260151422a4eadd25f60a825157'


def ensure_runner():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('RUNNER_OS') != 'Windows'):
        raise RuntimeError('Real installation tests require a disposable GitHub-hosted Windows runner.')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run():
    ensure_runner()  # Must precede file creation, download or process execution.
    report_dir = ROOT / 'artifacts' / 'ci'
    report_dir.mkdir(parents=True, exist_ok=True)
    target = Path(os.environ['RUNNER_TEMP']) / 'OVA Exporter GUI CI'
    if target.exists():
        raise RuntimeError('The installer test requires an unused target directory.')
    candidate = ROOT / 'dist' / f'OVA-Exporter-GUI-{VERSION}-Windows-x64-Setup.exe'
    # Check a fresh candidate installation separately from upgrading the public
    # baseline: success of one does not establish the other.
    fresh = Path(os.environ['RUNNER_TEMP']) / 'OVA Exporter GUI Fresh CI'
    if fresh.exists():
        raise RuntimeError('The fresh-install check requires an unused target directory.')
    subprocess.run([str(candidate), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                    '/SP-', f'/DIR={fresh}', f'/LOG={report_dir / "fresh-install.log"}'],
                   check=True, timeout=120)
    if (not (fresh / 'unins000.exe').is_file() or
            digest(fresh / 'OVAExporterGUI.exe') != digest(ROOT / 'dist' / 'OVAExporterGUI' / 'OVAExporterGUI.exe')):
        raise RuntimeError('The fresh installation does not match the candidate build.')
    fresh_report = report_dir / 'fresh-frozen-check.json'
    subprocess.run([str(fresh / 'OVAExporterGUI.exe'), '--self-test-report', str(fresh_report)],
                   check=True, timeout=60)
    if json.loads(fresh_report.read_text()).get('fake_ui_check') != 'passed':
        raise RuntimeError('The freshly installed app failed its guarded startup check.')
    subprocess.run([str(fresh / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                    '/NORESTART', f'/LOG={report_dir / "fresh-uninstall.log"}'],
                   check=True, timeout=120)
    if (fresh / 'OVAExporterGUI.exe').exists():
        raise RuntimeError('The fresh-install uninstaller left the executable behind.')
    baseline = Path(os.environ['RUNNER_TEMP']) / 'ova-baseline-2.3.1.exe'
    with urllib.request.urlopen(BASELINE_URL, timeout=60) as response:
        body = response.read(50_000_001)
    if len(body) > 50_000_000 or hashlib.sha256(body).hexdigest() != BASELINE_HASH:
        raise ValueError('Baseline download failed its pinned checksum check.')
    baseline.write_bytes(body)
    subprocess.run([str(baseline), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                    '/SP-', f'/DIR={target}', f'/LOG={report_dir / "baseline-install.log"}'],
                   check=True, timeout=120)
    installed = target / 'OVAExporterGUI.exe'
    if not installed.is_file() or not (target / 'unins000.exe').is_file():
        raise RuntimeError('The baseline did not install correctly.')

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = ctypes.c_int
    title = f'OVA Exporter GUI {VERSION}'
    if user32.FindWindowW(None, title):
        raise RuntimeError('Unexpected app instance existed before the isolated upgrade.')
    # Only this short-lived child is used for the parent-exit wait check.
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'])
    started = time.monotonic()
    subprocess.run([str(candidate), '/SILENT', '/NORESTART', '/SP-', '/OVAUPDATE=1',
                    f'/OVAPID={parent.pid}', f'/DIR={target}',
                    f'/LOG={report_dir / "upgrade-install.log"}'], check=True, timeout=120)
    parent.wait(timeout=10)
    if time.monotonic() - started < 3.5:
        raise RuntimeError('Setup did not wait for the simulated app parent to exit.')
    if digest(installed) != digest(ROOT / 'dist' / 'OVAExporterGUI' / 'OVAExporterGUI.exe'):
        raise RuntimeError('The upgraded executable does not match the candidate build.')
    deadline = time.monotonic() + 30
    window = None
    while time.monotonic() < deadline:
        window = user32.FindWindowW(None, title)
        if window:
            break
        time.sleep(0.25)
    if not window:
        raise RuntimeError('Setup completed but did not reopen the upgraded app.')
    user32.PostMessageW(window, 0x0010, 0, 0)  # Close the newly created, idle CI instance.
    deadline = time.monotonic() + 20
    while user32.FindWindowW(None, title) and time.monotonic() < deadline:
        time.sleep(0.25)
    if user32.FindWindowW(None, title):
        raise RuntimeError('The idle test app did not close; no process was force-stopped.')
    time.sleep(1)
    subprocess.run([str(target / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                    '/NORESTART', f'/LOG={report_dir / "uninstall.log"}'],
                   check=True, timeout=120)
    if installed.exists():
        raise RuntimeError('Uninstall did not remove the installed executable.')
    report = dict(baseline='2.3.1', candidate=VERSION, fresh_install='passed',
                  fresh_launch_self_test='passed', fresh_uninstall='passed',
                  parent_exit_wait='passed', upgrade='passed', reopen='passed',
                  uninstall='passed', vmware_connections='none',
                  scope='disposable GitHub-hosted Windows runner; not all Windows configurations')
    (report_dir / 'installer-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    run()
