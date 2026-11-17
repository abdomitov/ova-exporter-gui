"""macOS behavior, exercised on any OS by pretending to be macOS. No real Keychain is touched."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import platform_support
from secure_storage import MacKeychainProtection, WindowsDataProtection, default_protector
from tool_paths import find_ovftool
from updates import REPOSITORY, select_release


class FakeKeychain:
    """Mimics /usr/bin/security for one generic password."""
    def __init__(self, fail=False, value=None):
        self.value, self.fail, self.calls = value, fail, []

    def __call__(self, command):
        self.calls.append(command)
        assert command[0] == '/usr/bin/security' and 'OVA Exporter GUI' in command
        if self.fail:
            return SimpleNamespace(returncode=51, stdout='')
        if command[1] == 'find-generic-password':
            if self.value is None:
                return SimpleNamespace(returncode=44, stdout='')
            return SimpleNamespace(returncode=0, stdout=self.value + '\n')
        if command[1] == 'add-generic-password':
            self.value = command[command.index('-w') + 1]
            return SimpleNamespace(returncode=0, stdout='')
        raise AssertionError(command)


def mac():
    return patch.object(sys, 'platform', 'darwin')


class MacPlatformTests(unittest.TestCase):
    def test_names_locations_and_assets_follow_the_platform(self):
        with mac():
            self.assertEqual(platform_support.tool_name(), 'ovftool')
            self.assertEqual(platform_support.platform_label(), 'macOS')
            self.assertEqual(platform_support.installer_filename('2.5.0'), 'OVA-Exporter-GUI-2.5.0-macOS-Intel.dmg')
            self.assertEqual(platform_support.settings_directory(),
                             Path.home() / 'Library' / 'Application Support' / 'OVA Exporter')
            candidates = platform_support.tool_candidates('/app')
            self.assertIn(Path('/Applications/VMware OVF Tool/ovftool'), candidates)
            self.assertEqual(candidates[0], Path('/app/ovftool/ovftool'))
            self.assertFalse(any(path.name.endswith('.exe') for path in candidates))
            self.assertEqual(platform_support.shortcut_modifiers(), ('Control', 'Command'))
            self.assertIsInstance(default_protector(), MacKeychainProtection)
        with patch.object(sys, 'platform', 'win32'):
            self.assertEqual(platform_support.tool_name(), 'ovftool.exe')
            self.assertEqual(platform_support.installer_filename('2.5.0'),
                             'OVA-Exporter-GUI-2.5.0-Windows-x64-Setup.exe')
            self.assertIsInstance(default_protector(), WindowsDataProtection)

    def test_finds_an_installed_mac_tool(self):
        with mac(), patch('tool_paths.tool_file_exists', side_effect=lambda path: Path(path).as_posix().startswith('/Applications/VMware')):
            self.assertEqual(find_ovftool('/app'), Path('/Applications/VMware OVF Tool/ovftool'))

    def test_open_folder_uses_finder_without_a_shell(self):
        with mac(), patch.object(platform_support.os, 'startfile', create=True) as startfile, \
                patch('platform_support.subprocess.run') as run:
            platform_support.open_folder('/Users/me/Exports')
            startfile.assert_not_called()
        command = run.call_args.args[0]
        self.assertEqual(command, ['/usr/bin/open', '--', '/Users/me/Exports'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_mac_updater_only_offers_releases_with_a_mac_disk_image(self):
        def row(version, names):
            prefix = f'https://github.com/{REPOSITORY}/releases/download/v{version}/'
            return dict(tag_name='v' + version, draft=False, prerelease=False, body='',
                        html_url=f'https://github.com/{REPOSITORY}/releases/tag/v{version}',
                        assets=[dict(name=name, state='uploaded', size=1000, digest='sha256:' + 'a' * 64,
                                     browser_download_url=prefix + name) for name in names])
        windows_only = row('9.0.0', ['OVA-Exporter-GUI-9.0.0-Windows-x64-Setup.exe',
                                     'OVA-Exporter-GUI-9.0.0-Windows-x64-Setup.exe.sha256'])
        both = row('8.0.0', ['OVA-Exporter-GUI-8.0.0-Windows-x64-Setup.exe',
                             'OVA-Exporter-GUI-8.0.0-Windows-x64-Setup.exe.sha256',
                             'OVA-Exporter-GUI-8.0.0-macOS-Intel.dmg',
                             'OVA-Exporter-GUI-8.0.0-macOS-Intel.dmg.sha256'])
        with mac():
            release = select_release([windows_only, both], '1.0.0')
        self.assertEqual(release.version, '8.0.0')
        self.assertEqual(release.filename, 'OVA-Exporter-GUI-8.0.0-macOS-Intel.dmg')
        self.assertEqual(select_release([windows_only, both], '1.0.0').version, '9.0.0')


class KeychainProtectionTests(unittest.TestCase):
    def test_round_trip_creates_one_key_and_never_stores_plaintext(self):
        keychain = FakeKeychain()
        protection = MacKeychainProtection(keychain)
        secret = b'{"servers": ["vcenter.example.test"], "user": "administrator@vsphere.local"}'
        sealed = protection.protect(secret, 'connections')
        self.assertNotIn(b'vcenter', sealed)
        self.assertNotEqual(protection.protect(secret, 'connections'), sealed)  # fresh nonce every time
        self.assertEqual(protection.unprotect(sealed, 'connections'), secret)
        self.assertEqual(sum(call[1] == 'add-generic-password' for call in keychain.calls), 1)
        # A new process reads the same key from the Keychain.
        self.assertEqual(MacKeychainProtection(keychain).unprotect(sealed, 'connections'), secret)

    def test_tampering_wrong_purpose_and_other_key_are_rejected(self):
        keychain = FakeKeychain()
        protection = MacKeychainProtection(keychain)
        sealed = protection.protect(b'pinned certificate data', 'trust')
        flipped = sealed[:25] + bytes([sealed[25] ^ 1]) + sealed[26:]
        for data, purpose in ((flipped, 'trust'), (sealed, 'connections'), (b'DPAPI' + sealed, 'trust'),
                              (sealed[:30], 'trust')):
            with self.subTest(purpose=purpose, size=len(data)), self.assertRaises(OSError):
                protection.unprotect(data, purpose)
        other = MacKeychainProtection(FakeKeychain())
        with self.assertRaises(OSError):
            other.unprotect(sealed, 'trust')

    def test_unavailable_or_damaged_keychain_never_falls_back_to_plaintext(self):
        for keychain in (FakeKeychain(fail=True), FakeKeychain(value='not-a-key')):
            with self.subTest(value=keychain.value), self.assertRaises(OSError):
                MacKeychainProtection(keychain).protect(b'data', 'connections')
            self.assertFalse(any(call[1] == 'add-generic-password' for call in keychain.calls))
        with self.assertRaises(ValueError):
            MacKeychainProtection(FakeKeychain()).protect(b'', 'connections')

    def test_real_runner_uses_the_system_tool_without_a_shell(self):
        with patch('secure_storage.subprocess.run',
                   return_value=SimpleNamespace(returncode=0, stdout='ab' * 32)) as run:
            MacKeychainProtection().master_key()
        command, options = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(command[:2], ['/usr/bin/security', 'find-generic-password'])
        self.assertFalse(options.get('shell'))
        self.assertIn('timeout', options)


if __name__ == '__main__':
    unittest.main()
