"""Encrypted, allowlisted connection hints and certificate pins. No passwords."""
import base64
import json
import os
import re
import tempfile
from pathlib import Path

from vsphere import endpoint
from secure_storage import WindowsDataProtection


class ConnectionSettings:
    def __init__(self, directory=None, protector=None):
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        self.directory = Path(directory) if directory is not None else local / 'OVA Exporter'
        self.profiles_path = self.directory / 'connections.json'
        self.trust_path = self.directory / 'trusted_servers.json'
        self.protector = protector if protector is not None else WindowsDataProtection()

    @staticmethod
    def address(value):
        return endpoint(value)[2].casefold()

    @staticmethod
    def certificate_pin(value):
        compact = value.replace(':', '').upper()
        if not re.fullmatch('[0-9A-F]{64}', compact):
            raise ValueError('Invalid SHA-256 certificate fingerprint in saved trust settings.')
        return ':'.join(compact[index:index+2] for index in range(0, 64, 2))

    @staticmethod
    def read_document(path):
        try:
            if path.stat().st_size > 2_000_000:
                raise ValueError('Saved connection settings are unexpectedly large.')
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError:
            return None

    def read(self, path, key):
        data = self.read_document(path)
        if data is None:
            return []
        if isinstance(data, dict) and data.get('version') == 2:
            if set(data) != {'version', 'protection', 'payload'} or data.get('protection') != 'windows-dpapi-user':
                raise ValueError('Unsupported encrypted settings envelope.')
            if not isinstance(data.get('payload'), str):
                raise ValueError('Invalid encrypted settings payload.')
            try:
                ciphertext = base64.b64decode(data['payload'], validate=True)
                plaintext = self.protector.unprotect(ciphertext, key)
                data = json.loads(plaintext.decode('utf-8'))
            except (ValueError, UnicodeError):
                raise ValueError('Encrypted settings are damaged or have an invalid format.') from None
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get(key), list):
            raise ValueError('Saved connection settings have an unsupported format.')
        return data[key]

    def write(self, path, key, rows):
        allowed = {'connections': {'address', 'username'}, 'servers': {'address', 'sha256'}}
        if key not in allowed or any(not isinstance(row, dict) or set(row) != allowed[key] or
                                     any(not isinstance(value, str) for value in row.values()) for row in rows):
            raise ValueError('Only address/username or address/certificate-pin fields may be saved.')
        plaintext = json.dumps({'version': 1, key: rows}, ensure_ascii=False).encode('utf-8')
        if len(plaintext) > 1_000_000:
            raise ValueError('Saved connection settings are unexpectedly large.')
        ciphertext = self.protector.protect(plaintext, key)
        # Verify recovery before replacing an existing file. Both plaintext and
        # the verification copy stay in memory; temporary files are encrypted.
        if self.protector.unprotect(ciphertext, key) != plaintext:
            raise OSError('Settings encryption verification failed; the previous file was preserved.')
        document = {'version': 2, 'protection': 'windows-dpapi-user',
                    'payload': base64.b64encode(ciphertext).decode('ascii')}
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix=path.stem + '-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def migrate_legacy(self):
        """Replace legacy plaintext files only after encryption is verified."""
        migrated, errors = [], []
        for path, key in ((self.profiles_path, 'connections'), (self.trust_path, 'servers')):
            try:
                document = self.read_document(path)
                if document is None:
                    continue
                if isinstance(document, dict) and document.get('version') == 2:
                    self.read(path, key)  # Validate that this Windows account can decrypt it.
                    continue
                rows = self.profiles() if key == 'connections' else self.trusted_servers()
                self.write(path, key, rows)
                migrated.append(path.name)
            except (OSError, ValueError) as error:
                errors.append(path.name+': '+str(error))
        if errors:
            raise OSError('Saved-data encryption could not be completed: '+'; '.join(errors))
        return migrated

    def profiles(self):
        profiles = {}
        for row in self.read(self.profiles_path, 'connections'):
            # Explicitly exclude all unexpected keys, including credential or
            # session fields accidentally introduced by a future caller.
            if not isinstance(row, dict) or set(row) != {'address', 'username'}:
                continue
            address, username = row['address'], row['username']
            if not isinstance(address, str) or not isinstance(username, str):
                continue
            address, username = self.address(address), username.strip()
            if username:
                profiles[(address, username)] = {'address': address, 'username': username}
        return sorted(profiles.values(), key=lambda row: (row['address'], row['username'].casefold()))

    def remember_profile(self, address, username):
        address, username = self.address(address), username.strip()
        if not username:
            raise ValueError('A username is required to remember a server.')
        rows = self.profiles()
        rows = [row for row in rows if (row['address'], row['username']) != (address, username)]
        rows.append({'address': address, 'username': username})
        self.write(self.profiles_path, 'connections', rows)

    def forget_profile(self, address, username):
        address = self.address(address)
        rows = [row for row in self.profiles()
                if (row['address'], row['username']) != (address, username)]
        self.write(self.profiles_path, 'connections', rows)

    def trusted_pin(self, address):
        address = self.address(address)
        for row in self.read(self.trust_path, 'servers'):
            if not isinstance(row, dict) or set(row) != {'address', 'sha256'}:
                continue
            if not isinstance(row['address'], str) or not isinstance(row['sha256'], str):
                continue
            if self.address(row['address']) == address:
                return self.certificate_pin(row['sha256'])
        return None

    def trust_certificate(self, address, sha256):
        address, sha256 = self.address(address), self.certificate_pin(sha256)
        rows = self.trusted_servers()
        rows = [row for row in rows if row['address'] != address]
        rows.append({'address': address, 'sha256': sha256})
        self.write(self.trust_path, 'servers', rows)

    def trusted_servers(self):
        rows = []
        for row in self.read(self.trust_path, 'servers'):
            if not isinstance(row, dict) or set(row) != {'address', 'sha256'}:
                continue
            if isinstance(row['address'], str) and isinstance(row['sha256'], str):
                rows.append({'address': self.address(row['address']), 'sha256': self.certificate_pin(row['sha256'])})
        return rows

    def forget_trust(self, address):
        address = self.address(address)
        self.write(self.trust_path, 'servers',
                   [row for row in self.trusted_servers() if row['address'] != address])

    def clear_all(self):
        """Remove only this app's connection hints and certificate approvals."""
        errors = []
        for path in (self.profiles_path, self.trust_path):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                errors.append(str(error))
        if errors:
            raise OSError('; '.join(errors))
