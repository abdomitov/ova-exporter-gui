"""Exercise the real Inno update hooks using isolated files and no real app install.

The fixture disables uninstall registry entries and creates no shortcuts. Its
fake app is a text payload; a Python helper records the simulated app restart.
It never runs the production installer, accesses user settings or contacts VMware.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def check(iscc):
    directory = ROOT / 'artifacts' / ('installer-check-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    (directory / 'payload.txt').write_text('updated fixture payload', encoding='utf-8')
    (directory / 'record_reopen.py').write_text(
        'import json,sys\nfrom pathlib import Path\n'
        'folder=Path(sys.argv[1])\n'
        '(folder/"reopened.json").write_text(json.dumps({"payload":'
        '(folder/"OVAExporterGUI.exe").read_text()}))\n', encoding='utf-8')
    code = (ROOT / 'packaging/windows.iss').read_text(encoding='utf-8').split('[Code]', 1)[1]
    fixture = rf'''[Setup]
AppId=OVAExporterFixture-{uuid.uuid4().hex}
AppName=OVA Exporter isolated update fixture
AppVersion=1.0.0
DefaultDirName={{src}}\fixture
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
DisableStartupPrompt=yes
CloseApplications=no
RestartApplications=no
OutputDir=.
OutputBaseFilename=fixture-setup
[Files]
Source: "payload.txt"; DestDir: "{{app}}"; DestName: "OVAExporterGUI.exe"; Flags: ignoreversion
[Run]
Filename: "{sys.executable}"; Parameters: """{{src}}\record_reopen.py"" ""{{app}}"""; Flags: runhidden; Check: IsAppUpdate
[Code]
{code}
'''
    script = directory / 'fixture.iss'
    script.write_text(fixture, encoding='utf-8-sig')
    compiled = subprocess.run([str(iscc), str(script)], capture_output=True, text=True)
    (directory / 'compile.txt').write_text(compiled.stdout + compiled.stderr, encoding='utf-8')
    if compiled.returncode:
        raise RuntimeError('Fixture compiler failed: ' + compiled.stdout[-1000:] + compiled.stderr[-1000:])

    def run(name, *, installed=True, pid=None):
        target = directory / name
        target.mkdir()
        if installed:
            (target / 'OVAExporterGUI.exe').write_text('old fixture payload')
            (target / 'unins000.exe').write_text('fixture marker; never executed')
        arguments = [str(directory / 'fixture-setup.exe'), '/VERYSILENT', '/SP-',
                     '/SUPPRESSMSGBOXES', '/NORESTART', '/OVAUPDATE=1', f'/DIR={target}']
        if pid is not None:
            arguments.append(f'/OVAPID={pid}')
        result = subprocess.run(arguments, capture_output=True, timeout=45)
        return target, result.returncode

    # The parent is a short-lived fixture, not the installed app. Production code
    # must wait for it to exit, replace the payload, then run the reopen helper.
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'])
    started = time.monotonic()
    target, result = run('success', pid=parent.pid)
    parent.wait(timeout=10)
    assert result == 0, f'Update fixture exit: {result}'
    assert time.monotonic() - started >= 3.5, 'Setup did not wait for its parent'
    assert json.loads((target / 'reopened.json').read_text())['payload'] == 'updated fixture payload'
    target, result = run('missing-pid')
    assert result != 0 and not (target / 'reopened.json').exists()
    assert (target / 'OVAExporterGUI.exe').read_text() == 'old fixture payload'
    target, result = run('missing-install', installed=False, pid=parent.pid)
    assert result != 0 and not (target / 'reopened.json').exists()
    assert not (target / 'OVAExporterGUI.exe').exists()
    print('PASS: native installer hooks wait for parent, update payload and reopen; '
          'missing installation/PID fail before writing. No real install/registry/shortcuts.')
    return directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', required=True, type=Path)
    print(check(parser.parse_args().iscc))
