"""OVA process runner and manifest verification."""
import hashlib
import re
import tarfile
from collections import deque
from pathlib import PurePosixPath


def archive_name_key(name):
    """Reject ambiguous paths before declaring an archive verified."""
    parts = name.split('/')
    if (not name or name.startswith('/') or '\\' in name or ':' in name or
            any(ord(char) < 32 for char in name) or '..' in parts or
            any(part.rstrip(' .') != part for part in parts if part != '.')):
        raise ValueError('Unsafe OVA member path: ' + name)
    return str(PurePosixPath(name)).casefold()


def export_command(tool, authority, vm_id, ticket, thumbprint, output):
    return [str(tool), '--machineOutput', f'--I:sourceSessionTicket={ticket}',
            f'--sourceSSLThumbprint={thumbprint}',
            f'vi://{authority}/?moref=vim.VirtualMachine:{vm_id}', str(output)]


def progress_value(line):
    match = re.search(r'(?:PROGRESS\s*[:=]?\s*|Disk progress:\s*)(\d+(?:\.\d+)?)', line, re.I)
    return min(100, float(match.group(1))) if match else None


class ProgressParser:
    """OVF Tool emits a section header followed by '+ value' records."""
    def __init__(self):
        self.section = ''

    def feed(self, line):
        direct = progress_value(line)
        if direct is not None:
            return direct
        if re.fullmatch(r'[A-Z][A-Z_]*', line):
            self.section = line
        if self.section == 'PROGRESS':
            match = re.fullmatch(r'\+\s*(\d+(?:\.\d+)?)', line)
            if match:
                return max(0, min(100, float(match.group(1))))
        return None


class TransferTracker:
    """Rolling five-second rate, including time spent stalled."""
    def __init__(self, started):
        self.started = started
        self.samples = deque([(started, 0)])

    def sample(self, now, size):
        self.samples.append((now, max(0, size)))
        while len(self.samples) > 2 and self.samples[1][0] <= now - 5:
            self.samples.popleft()
        oldest, previous = self.samples[0]
        rate = max(0, size - previous) / (now - oldest) if now > oldest else 0
        return {'bytes': size, 'speed': rate, 'elapsed': max(0, now - self.started)}


def verify_ova(path, status=lambda value: None, cancel_check=lambda: None):
    """Stream all package members and verify manifest hashes without extracting."""
    hashes = {}
    manifests = []
    descriptor = False
    disk = False
    seen = set()
    archive_input = {'fileobj': path} if hasattr(path, 'read') else {'name': path}
    with tarfile.open(mode='r|', **archive_input) as archive:
        for index, member in enumerate(archive):
            cancel_check()
            if not member.isfile():
                raise ValueError('OVA contains a non-file entry.')
            key = archive_name_key(member.name)
            if key in seen:
                raise ValueError('Duplicate or ambiguous OVA member: ' + member.name)
            seen.add(key)
            if index == 0 and not member.name.lower().endswith('.ovf'):
                raise ValueError('OVA does not begin with an OVF descriptor.')
            status('Checking ' + member.name)
            descriptor |= member.name.lower().endswith('.ovf')
            disk |= member.name.lower().endswith('.vmdk')
            stream = archive.extractfile(member)
            if member.name.lower().endswith('.mf'):
                if member.size > 2_000_000:
                    raise ValueError('Unexpectedly large manifest.')
                manifests.append(stream.read().decode('utf-8-sig'))
                continue
            digests = {name: hashlib.new(name) for name in ('sha1', 'sha256', 'sha512')}
            read = 0
            while chunk := stream.read(4 * 1024 * 1024):
                cancel_check()
                read += len(chunk)
                for digest in digests.values():
                    digest.update(chunk)
            if read != member.size:
                raise ValueError('Incomplete OVA member: ' + member.name)
            hashes[member.name] = {k: v.hexdigest() for k, v in digests.items()}
    if not descriptor or not disk:
        raise ValueError('OVA is missing its descriptor or virtual disk.')
    checked = set()
    for manifest in manifests:
        for line in manifest.splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r'(SHA1|SHA256|SHA512)\((.+)\)\s*=\s*([0-9a-fA-F]+)\s*', line)
            if not match:
                raise ValueError('Unsupported manifest entry.')
            algorithm, name, expected = match.groups()
            actual = hashes.get(name, {}).get(algorithm.lower())
            if actual is None or actual != expected.lower():
                raise ValueError('Checksum mismatch or missing file: ' + name)
            checked.add(name)
    if not manifests or not set(hashes).issubset(checked):
        raise ValueError('The OVA manifest does not cover every payload file.')
    return len(checked)
