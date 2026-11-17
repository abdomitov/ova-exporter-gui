"""Decide whether a push is a new version, and publish it only after every build check passed.

Actions: ``plan`` (is this a new version?), ``verify-build`` and ``verify-macos`` (check the built
files and write their manifests) and ``publish`` (create the public release from those exact files). This tool never
replaces assets, moves a tag or overwrites an existing release.
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


def macos_files(version):
    if not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', version):
        raise ValueError('Release versions must contain three numeric components.')
    image = f'OVA-Exporter-GUI-{version}-macOS-Intel.dmg'
    return (image, image + '.sha256')


def verify_files(directory, version, names=None):
    directory = Path(directory)
    names = names or expected_files(version)
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < 300 * 1024**2:
            raise ValueError('Missing or invalid release file: ' + name)
    for name in names[::2]:
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


def verify_macos():
    """Check the macOS disk image and its CI reports; write ``macos-manifest.json``."""
    directory = ROOT / 'dist'
    files = verify_files(directory, VERSION, macos_files(VERSION))
    frozen = json.loads((ROOT / 'artifacts/ci/macos-frozen.json').read_text())
    image = json.loads((ROOT / 'artifacts/ci/macos-dmg-check.json').read_text())
    if frozen.get('fake_ui_check') != 'passed' or image.get('version') != VERSION:
        raise ValueError('Required macOS check reports are absent or mismatched.')
    for check in MACOS_CHECKS:
        if image.get(check) != 'passed':
            raise ValueError('macOS disk image check did not pass: ' + check)
    commit = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Missing exact GitHub build commit.')
    manifest = dict(schema=1, platform='macos-x86_64', version=VERSION, commit=commit,
                    repository=os.environ['GITHUB_REPOSITORY'], run_id=os.environ['GITHUB_RUN_ID'],
                    python=sys.version.split()[0], signing='ad-hoc, not notarized', files=files,
                    checks=dict(frozen='passed', disk_image=image))
    (directory / 'macos-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('PASS: macOS disk image, checksum and required reports verified.')


MACOS_CHECKS = ('mounted', 'layout', 'signature', 'architecture', 'bundle_version', 'installed_self_test')


def parse_version(text):
    match = re.fullmatch(r'v?(\d{1,5})\.(\d{1,5})\.(\d{1,5})', text or '')
    return tuple(int(part) for part in match.groups()) if match else None


def decide_release(version, tags):
    """Return ``(should_release, reason, previous_tag)`` for the app version in this checkout."""
    wanted = parse_version(version)
    if wanted is None:
        raise ValueError('The app version must contain three numeric components.')
    known = {tag: parse_version(tag) for tag in tags if parse_version(tag)}
    previous = max(known, key=known.get, default='')
    if 'v' + version in known:
        return False, f'v{version} is already released; this push only runs the tests.', previous
    if previous and wanted < known[previous]:
        raise ValueError(f'Version {version} is lower than the existing {previous}. Raise VERSION before merging.')
    return True, f'v{version} is new (previous: {previous or "none"}).', previous


def gh_json(*args):
    return json.loads(subprocess.check_output(['gh', 'api', *args], text=True))


def existing_tags(repository):
    refs = subprocess.check_output(['gh', 'api', '--paginate', f'repos/{repository}/git/matching-refs/tags/v',
                                    '--jq', '.[].ref'], text=True).split()
    tags = {ref.removeprefix('refs/tags/') for ref in refs}
    # Drafts have no tag yet, but they still reserve their version.
    tags |= {row['tag_name'] for row in gh_json(f'repos/{repository}/releases?per_page=100')}
    return sorted(tags)


def plan():
    """Write ``release``, ``version``, ``tag`` and ``previous`` for later workflow jobs."""
    repository = os.environ['GITHUB_REPOSITORY']
    release, reason, previous = decide_release(VERSION, existing_tags(repository))
    print(reason)
    lines = [f'release={"true" if release else "false"}', f'version={VERSION}',
             f'tag=v{VERSION}', f'previous={previous}']
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as stream:
                stream.write(f'\n### Release plan\n\n{reason}\n')


def release_assets(version):
    return (*expected_files(version), *macos_files(version), 'build-manifest.json', 'macos-manifest.json')


class Superseded(Exception):
    """Not an error: another run or a newer commit owns this release."""


def release_notes(repository, tag, commit, previous, manifest):
    header = (f'Built from `{commit}` by [GitHub Actions](https://github.com/{repository}/actions/runs/'
              f'{manifest["run_id"]}).\n\n'
              'Checked before publishing: the test suite on Python 3.10 and 3.14, the frozen app self-test, '
              'and fresh install, upgrade, reopen and uninstall on a clean Windows runner.\n\n'
              'The installer is not code-signed yet, so Windows SmartScreen may show a warning; compare the '
              'SHA-256 in the `.sha256` file before choosing **Run anyway**. Live VMware export and '
              'cancellation are not covered by automated tests.\n\n')
    try:
        command = ['repos/' + repository + '/releases/generate-notes', '-X', 'POST',
                   '-f', 'tag_name=' + tag, '-f', 'target_commitish=' + commit]
        if previous:
            command += ['-f', 'previous_tag_name=' + previous]
        generated = gh_json(*command).get('body', '')
    except (subprocess.CalledProcessError, ValueError, OSError):
        generated = ''
    return header + (generated or 'See the commit history for changes since the previous release.') + '\n'


def publish(directory):
    """Create the public release for this exact commit. Runs only in the main-branch pipeline."""
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch')
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise RuntimeError('Publishing is limited to the main-branch pipeline.')
    directory = Path(directory)
    repository = os.environ['GITHUB_REPOSITORY']
    commit = os.environ.get('GITHUB_SHA', '')
    tag = 'v' + VERSION
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Missing exact GitHub build commit.')
    manifest = json.loads((directory / 'build-manifest.json').read_text())
    if (manifest.get('version') != VERSION or manifest.get('commit') != commit
            or manifest.get('repository') != repository
            or str(manifest.get('run_id')) != os.environ.get('GITHUB_RUN_ID')):
        raise ValueError('The build manifest does not belong to this commit and workflow run.')
    if manifest.get('files') != verify_files(directory, VERSION):
        raise ValueError('Downloaded files differ from the build manifest.')
    verify_source(directory / f'ova-exporter-gui-{VERSION}-source.zip', VERSION)
    mac = json.loads((directory / 'macos-manifest.json').read_text())
    if (mac.get('version') != VERSION or mac.get('commit') != commit
            or mac.get('repository') != repository or str(mac.get('run_id')) != os.environ.get('GITHUB_RUN_ID')):
        raise ValueError('The macOS manifest does not belong to this commit and workflow run.')
    if mac.get('files') != verify_files(directory, VERSION, macos_files(VERSION)):
        raise ValueError('Downloaded macOS files differ from their manifest.')
    if mac.get('checks', {}).get('frozen') != 'passed' or any(
            mac.get('checks', {}).get('disk_image', {}).get(name) != 'passed' for name in MACOS_CHECKS):
        raise ValueError('Required macOS build evidence is missing or did not pass.')
    checks = manifest.get('checks', {})
    native = checks.get('installer', {})
    if checks.get('frozen') != 'passed' or checks.get('source') != 'passed' or any(
            native.get(name) != 'passed' for name in
            ('fresh_install', 'fresh_launch_self_test', 'fresh_uninstall',
             'parent_exit_wait', 'upgrade', 'reopen', 'uninstall')):
        raise ValueError('Required build evidence is missing or did not pass.')
    tags = existing_tags(repository)
    release, reason, previous = decide_release(VERSION, tags)
    if not release:
        raise Superseded(reason)
    if gh_json(f'repos/{repository}/git/ref/heads/main')['object']['sha'] != commit:
        raise Superseded('Main has a newer commit; its own pipeline run will publish if needed.')
    notes = directory / 'release-notes.md'
    notes.write_text(release_notes(repository, tag, commit, previous, manifest), encoding='utf-8')
    subprocess.run(['gh', 'release', 'create', tag, '--repo', repository, '--target', commit,
                    '--title', f'v{VERSION}', '--notes-file', str(notes),
                    *(str(directory / name) for name in release_assets(VERSION))], check=True)  # Never --clobber.
    row = gh_json(f'repos/{repository}/releases/tags/{tag}')
    names = {asset['name'] for asset in row.get('assets', [])}
    if row.get('draft') or names != set(release_assets(VERSION)):
        raise ValueError('The published release does not contain exactly the expected files.')
    print(f'Published {tag}: {row.get("html_url", "")}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'verify-build', 'verify-macos', 'publish'))
    parser.add_argument('--directory', type=Path, default=ROOT / 'dist')
    options = parser.parse_args()
    if options.action == 'plan':
        plan()
    elif options.action == 'verify-build':
        verify_build()
    elif options.action == 'verify-macos':
        verify_macos()
    else:
        try:
            publish(options.directory)
        except Superseded as reason:
            print('Nothing published:', reason)
