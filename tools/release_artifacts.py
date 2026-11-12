"""Validate bounded, allowlisted release files; optionally create a new draft.

This tool never publishes a release, replaces assets or changes a release tag.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from metadata import VERSION  # noqa: E402 - standalone script bootstraps source paths above
from tools.package_source import ROOT_FILES, EXTRA_FILES, OPTIONAL_IMAGES  # noqa: E402


def sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(data)
    return hasher.hexdigest()


def expected_files(version):
    if not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', version):
        raise ValueError('Release versions must contain three numeric components.')
    installer = f'OVA-Exporter-GUI-{version}-Windows-x64-Setup.exe'
    source = f'ova-exporter-gui-{version}-source.zip'
    return (installer, installer + '.sha256', source, source + '.sha256')


def verify_files(directory, version):
    directory = Path(directory)
    names = expected_files(version)
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < 300 * 1024**2:
            raise ValueError('Missing or invalid release file: ' + name)
    for name in (names[0], names[2]):
        expected = sha256(directory / name) + '  ' + name
        if (directory / (name + '.sha256')).read_text(encoding='ascii').strip() != expected:
            raise ValueError('Checksum sidecar mismatch: ' + name)
    return {name: dict(size=(directory / name).stat().st_size, sha256=sha256(directory / name))
            for name in names}


def verify_source(archive, version):
    names = [*ROOT_FILES, *EXTRA_FILES,
             *(name for name in OPTIONAL_IMAGES if (ROOT / name).is_file())]
    prefix = f'ova-exporter-gui-{version}/'
    with zipfile.ZipFile(archive) as zipped:
        if (sum(item.file_size for item in zipped.infolist()) > 50_000_000
                or sorted(zipped.namelist()) != sorted(prefix + name for name in names)):
            raise ValueError('Source archive failed its size/allowlist check.')
        if zipped.testzip() is not None:
            raise ValueError('Source archive failed its CRC/allowlist check.')
        for name in names:
            payload = zipped.read(prefix + name)
            if payload != (ROOT / name).read_bytes():
                raise ValueError('Source archive differs from this checkout: ' + name)
            if name.endswith(('.py', '.pyw')):
                compile(payload, name, 'exec')


def verify_build():
    directory = ROOT / 'dist'
    files = verify_files(directory, VERSION)
    verify_source(directory / f'ova-exporter-gui-{VERSION}-source.zip', VERSION)
    issuer = (ROOT / 'packaging' / 'windows.iss').read_text()
    if f'#define AppVersion "{VERSION}"' not in issuer:
        raise ValueError('App and installer fallback versions differ.')
    forbidden = {'ovftool.exe', 'vmacore.dll', 'vmomi.dll', 'vim-types.dll'}
    if any(path.name.lower() in forbidden for path in (directory / 'OVAExporterGUI').rglob('*')):
        raise ValueError('Proprietary VMware runtime found in the public app bundle.')
    frozen = json.loads((ROOT / 'artifacts/ci/frozen-check.json').read_text())
    native = json.loads((ROOT / 'artifacts/ci/installer-check.json').read_text())
    if frozen.get('fake_ui_check') != 'passed' or native.get('candidate') != VERSION:
        raise ValueError('Required build check reports are absent or mismatched.')
    for check in ('fresh_install', 'fresh_launch_self_test', 'fresh_uninstall',
                  'parent_exit_wait', 'upgrade', 'reopen', 'uninstall'):
        if native.get(check) != 'passed':
            raise ValueError('Installer check did not pass: ' + check)
    commit = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Missing exact GitHub build commit.')
    manifest = dict(schema=1, version=VERSION, commit=commit,
                    repository=os.environ['GITHUB_REPOSITORY'], run_id=os.environ['GITHUB_RUN_ID'],
                    python=sys.version.split()[0], openssl=ssl.OPENSSL_VERSION,
                    installer_signing='unsigned', files=files,
                    checks=dict(frozen='passed', installer=native, source='passed'))
    (directory / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write(f'\n## Candidate {VERSION}\n\nCommit: `{commit}`\n\n'
                         'Installer, source ZIP, checksums, frozen check and native install/upgrade/reopen/uninstall passed. '
                         'Unsigned; VMware live operation is untested. Artifact upload is not a public app update.\n')
    print('PASS: exact release files, source allowlist and required build reports verified.')


def create_draft(directory):
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise RuntimeError('Draft creation requires an explicit main-branch workflow dispatch.')
    directory = Path(directory)
    manifest = json.loads((directory / 'build-manifest.json').read_text())
    if (manifest.get('version') != VERSION or manifest.get('commit') != os.environ.get('GITHUB_SHA')
            or manifest.get('repository') != os.environ.get('GITHUB_REPOSITORY')):
        raise ValueError('Build manifest does not belong to the selected source commit.')
    if manifest.get('files') != verify_files(directory, VERSION):
        raise ValueError('Downloaded artifact files differ from the build manifest.')
    verify_source(directory / f'ova-exporter-gui-{VERSION}-source.zip', VERSION)
    notes = directory / 'draft-notes.md'
    notes.write_text(f'## Release candidate {VERSION}\n\n'
                     f'Built from `{manifest["commit"]}` by [GitHub Actions]('
                     f'https://github.com/{manifest["repository"]}/actions/runs/{manifest["run_id"]}).\n\n'
                     'Draft only: review user-facing changes, installer behavior and these exact checksums '
                     'before publishing. Publishing makes this version discoverable to installed updaters, '
                     'including when marked prerelease. The installer is unsigned; no live VMware testing '
                     'or signing certification is implied. Add the actual release changes before publication.\n', encoding='utf-8')
    command = ['gh', 'release', 'create', 'v' + VERSION, '--repo', manifest['repository'],
               '--target', manifest['commit'], '--draft', '--prerelease', '--title',
               f'v{VERSION} — Windows preview candidate', '--notes-file', str(notes),
               *(str(directory / name) for name in expected_files(VERSION)),
               str(directory / 'build-manifest.json')]
    subprocess.run(command, check=True)  # Existing versions fail; never use upload --clobber.


def validate_publish_choice(tag, commit, confirmed):
    if (confirmed != 'true' or tag != 'v' + VERSION
            or not re.fullmatch('[0-9a-f]{40}', commit or '')):
        raise ValueError('Publishing requires explicit confirmation, the current app tag and an exact commit.')


def reviewed_draft(rows, tag, commit):
    """Drafts require the authenticated release list, not the published-tag API."""
    matches = [row for row in rows if isinstance(row, dict) and row.get('tag_name') == tag] if isinstance(rows, list) else []
    if (len(matches) != 1 or matches[0].get('draft') is not True
            or matches[0].get('target_commitish') != commit):
        raise ValueError('This must be a new draft targeting the exact reviewed commit.')
    return matches[0]


def publish_reviewed():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise RuntimeError('Publishing requires an explicit main-branch workflow dispatch.')
    tag = os.environ.get('OVA_RELEASE_TAG', '')
    commit = os.environ.get('OVA_RELEASE_COMMIT', '')
    validate_publish_choice(tag, commit, os.environ.get('OVA_CONFIRM_PUBLISH'))
    if commit != os.environ['GITHUB_SHA']:
        raise ValueError('The reviewed candidate is not the selected main-branch commit. Rebuild/review it.')
    repository = os.environ['GITHUB_REPOSITORY']
    def api(path):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/{path}'], text=True))
    if api('git/ref/heads/main')['object']['sha'] != commit:
        raise ValueError('Main moved after this workflow started. Rebuild/review the newer source.')
    # GET releases/tags/{tag} does not find an unpublished draft without a tag.
    # Fail closed if the exact draft is not among the 100 most recent releases.
    reviewed_draft(api('releases?per_page=100'), tag, commit)
    directory = Path(tempfile.mkdtemp(prefix='ova-reviewed-release-', dir=os.environ['RUNNER_TEMP']))
    command = ['gh', 'release', 'download', tag, '--repo', repository, '--dir', str(directory)]
    for name in (*expected_files(VERSION), 'build-manifest.json'):
        command.extend(['--pattern', name])
    subprocess.run(command, check=True)
    manifest = json.loads((directory / 'build-manifest.json').read_text())
    if (manifest.get('commit') != commit or manifest.get('version') != VERSION
            or manifest.get('repository') != repository
            or manifest.get('files') != verify_files(directory, VERSION)):
        raise ValueError('The reviewed release does not match its exact build manifest.')
    verify_source(directory / f'ova-exporter-gui-{VERSION}-source.zip', VERSION)
    checks = manifest.get('checks', {})
    native = checks.get('installer', {})
    if checks.get('frozen') != 'passed' or checks.get('source') != 'passed':
        raise ValueError('Required build evidence is missing.')
    if any(native.get(name) != 'passed' for name in
           ('fresh_install', 'fresh_launch_self_test', 'fresh_uninstall',
            'parent_exit_wait', 'upgrade', 'reopen', 'uninstall')):
        raise ValueError('Installer validation did not pass.')
    run_id = str(manifest.get('run_id', ''))
    if not run_id.isdigit():
        raise ValueError('Invalid build run identity.')
    run = api('actions/runs/' + run_id)
    if (run.get('conclusion') != 'success' or run.get('head_sha') != commit
            or run.get('path') != '.github/workflows/release-build.yml'):
        raise ValueError('The referenced release build did not succeed for this commit.')
    # Recheck immediately before the only mutation. No --latest/asset replacement,
    # tag movement or version change is performed by the publish workflow.
    if api('git/ref/heads/main')['object']['sha'] != commit:
        raise ValueError('Main changed during review validation; refusing to publish.')
    subprocess.run(['gh', 'release', 'edit', tag, '--repo', repository, '--draft=false'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify-build', 'create-draft', 'publish-reviewed'))
    parser.add_argument('--directory', type=Path, default=ROOT / 'dist')
    options = parser.parse_args()
    if options.action == 'verify-build':
        verify_build()
    elif options.action == 'create-draft':
        create_draft(options.directory)
    else:
        publish_reviewed()
