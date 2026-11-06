"""Public GitHub release checks and verified, user-confirmed Windows updates.

No VMware credentials, connection hints or GitHub tokens are used here.
Checks never execute downloads; the UI separately authorizes installation.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = 'abdomitov/ova-exporter-gui'
RELEASES_URL = f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=30'
MAX_INSTALLER = 300 * 1024 * 1024
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com',
                  'objects.githubusercontent.com'}


def version_tuple(value):
    """Accept our numeric release tags only; avoid lexical ordering and downgrades."""
    if not isinstance(value, str) or not re.fullmatch(r'v?\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('Unsupported release version.')
    return tuple(map(int, value.removeprefix('v').split('.')))


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    installer_url: str
    checksum_url: str
    filename: str
    size: int
    digest: str
    preview: bool
    notes: str


def select_release(rows, current, skipped=''):
    if not isinstance(rows, list):
        raise ValueError('GitHub returned an unexpected release list.')
    candidates = []
    current_version = version_tuple(current)
    for row in rows:
        if not isinstance(row, dict) or row.get('draft') is not False:
            continue
        try:
            tag = row['tag_name']
            number = version_tuple(tag)
            version = tag.removeprefix('v')
            if number <= current_version:
                continue
            filename = f'OVA-Exporter-GUI-{version}-Windows-x64-Setup.exe'
            prefix = f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
            page = f'https://github.com/{REPOSITORY}/releases/tag/{tag}'
            assets = row['assets']
            if not isinstance(assets, list) or row.get('html_url') != page:
                continue
            files = {asset['name']: asset for asset in assets
                     if isinstance(asset, dict) and isinstance(asset.get('name'), str)
                     and asset.get('state') == 'uploaded'}
            installer, checksum = files[filename], files[filename + '.sha256']
            size = installer['size']
            if type(size) is not int or not 0 < size <= MAX_INSTALLER:
                continue
            if installer['browser_download_url'] != prefix + filename:
                continue
            if checksum['browser_download_url'] != prefix + filename + '.sha256':
                continue
            digest = installer.get('digest') or ''
            if digest and not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
                continue
            notes = row.get('body') or ''
            candidates.append((number, Release(version, page, prefix + filename,
                               prefix + filename + '.sha256', filename, size,
                               digest.removeprefix('sha256:').lower(),
                               bool(row.get('prerelease')), str(notes)[:1500])))
        except (KeyError, TypeError, ValueError):
            continue  # Drafts, source-only and malformed releases are never executable updates.
    latest = max(candidates, key=lambda item: item[0])[1] if candidates else None
    return None if latest and latest.version == skipped else latest


def safe_url(url, *, api=False):
    parts = urlsplit(url)
    hosts = {'api.github.com'} if api else DOWNLOAD_HOSTS
    if (parts.scheme != 'https' or parts.hostname not in hosts or parts.username
            or parts.password or parts.port not in (None, 443) or parts.fragment):
        raise ValueError('The update URL is outside the permitted GitHub HTTPS hosts.')
    return url


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        safe_url(new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


class UpdateClient:
    def __init__(self, opener=None):
        self.opener = opener or build_opener(GitHubRedirect())

    def open(self, url, *, api=False):
        safe_url(url, api=api)
        request = Request(url, headers={
            'User-Agent': 'OVA-Exporter-GUI-update-check',
            'Accept': 'application/vnd.github+json' if api else 'application/octet-stream',
        })
        response = self.opener.open(request, timeout=15)
        try:
            safe_url(response.geturl(), api=api)
        except Exception:
            response.close()
            raise
        return response

    def check(self, current, skipped=''):
        with self.open(RELEASES_URL, api=True) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('GitHub release metadata is unexpectedly large.')
        return select_release(json.loads(body), current, skipped)

    def download(self, release, directory, progress=lambda current, total: None):
        # Even a caller-supplied Release must belong to this repository.
        version_tuple(release.version)
        expected_name = f'OVA-Exporter-GUI-{release.version}-Windows-x64-Setup.exe'
        if (release.filename != expected_name or type(release.size) is not int
                or not 0 < release.size <= MAX_INSTALLER):
            raise ValueError('Invalid installer metadata.')
        prefixes = [f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
                    for tag in (release.version, 'v' + release.version)]
        if not any(release.installer_url == prefix + expected_name and
                   release.checksum_url == prefix + expected_name + '.sha256' for prefix in prefixes):
            raise ValueError('Installer must come from this project\'s release.')
        with self.open(release.checksum_url) as response:
            content = response.read(4097)
        if len(content) > 4096:
            raise ValueError('Invalid installer checksum file.')
        match = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?' + re.escape(expected_name) + r'\s*',
                             content.decode('ascii'))
        if not match:
            raise ValueError('Invalid installer checksum file.')
        digest = match[1].lower()
        if release.digest and digest != release.digest:
            raise ValueError('GitHub and the release checksum disagree.')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='download-', dir=directory))
        partial = folder / (expected_name + '.partial')
        final = folder / expected_name
        started, last_notice = time.monotonic(), 0.0
        try:
            total, hasher = 0, hashlib.sha256()
            with self.open(release.installer_url) as response, partial.open('xb') as stream:
                while True:
                    if time.monotonic() - started > 600:
                        raise TimeoutError('The update download timed out. Please try again.')
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > release.size:
                        raise ValueError('Installer exceeds its published size.')
                    stream.write(chunk)
                    hasher.update(chunk)
                    now = time.monotonic()
                    if now - last_notice >= 0.25:
                        progress(total, release.size)
                        last_notice = now
            if total != release.size or hasher.hexdigest() != digest:
                raise ValueError('Installer size or SHA-256 checksum verification failed.')
            partial.replace(final)
            progress(total, release.size)
            return final, digest
        except Exception:
            partial.unlink(missing_ok=True)
            folder.rmdir()
            raise


def verify_installer(path, release, digest):
    """Recheck immediately before launch; a downloaded file may have changed."""
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Missing verified installer checksum.')
    path = Path(path)
    hasher = hashlib.sha256()
    if path.name != release.filename or path.stat().st_size != release.size:
        raise ValueError('Downloaded installer has changed; download it again.')
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b''):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError('Downloaded installer has changed; download it again.')


class UpdatePreferences:
    """Only update choices are persisted. No addresses, usernames or passwords."""
    def __init__(self, directory=None):
        self.path = Path(directory) / 'updates.json' if directory is not None else None
        self.automatic, self.skipped, self.remind_after = True, '', 0.0
        if self.path is not None:
            try:
                if self.path.stat().st_size > 4096:
                    return
                data = json.loads(self.path.read_text(encoding='utf-8'))
                self.automatic = data.get('automatic', True) is not False
                skipped = data.get('skipped', '')
                if skipped:
                    version_tuple(skipped)
                    self.skipped = skipped.removeprefix('v')
                reminder = data.get('remind_after', 0)
                if type(reminder) in (int, float) and 0 <= reminder <= time.time() + 86400:
                    self.remind_after = reminder
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='updates-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(dict(automatic=self.automatic, skipped=self.skipped,
                               remind_after=self.remind_after), stream)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def due(self):
        return self.automatic and time.time() >= self.remind_after
