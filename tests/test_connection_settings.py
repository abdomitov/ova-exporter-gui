"""Offline privacy and certificate-pin regressions; no server access.

Use only temporary directories and FakeProtection; never real profile settings.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connection_settings import ConnectionSettings


class FakeProtection:
    """Reversible test fixture only; production always uses Windows DPAPI."""
    def protect(self, data, purpose):
        return b'TEST-ONLY\0'+purpose.encode('ascii')+b'\0'+data[::-1]

    def unprotect(self, data, purpose):
        prefix=b'TEST-ONLY\0'+purpose.encode('ascii')+b'\0'
        if not data.startswith(prefix):
            raise OSError('Simulated wrong-purpose or corrupted ciphertext')
        return data[len(prefix):][::-1]


class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ConnectionSettings(Path(temporary.name) / 'settings',protector=FakeProtection())

    def test_reading_defaults_does_not_create_any_settings(self):
        self.assertEqual(self.store.profiles(), [])
        self.assertIsNone(self.store.trusted_pin('example.test'))
        self.assertFalse(self.store.directory.exists())

    def test_profiles_store_only_address_and_username(self):
        self.store.remember_profile('https://EXAMPLE.test:443/ui', ' root ')
        data = json.loads(self.store.profiles_path.read_text(encoding='utf-8'))
        self.assertEqual(set(data),{'version','protection','payload'})
        self.assertEqual(data['version'],2)
        self.assertEqual(data['protection'],'windows-dpapi-user')
        self.assertEqual(self.store.profiles(),[{'address':'example.test','username':'root'}])
        self.assertNotIn('example.test',self.store.profiles_path.read_text(encoding='utf-8'))
        self.assertFalse(self.store.trust_path.exists())
        with self.assertRaises(ValueError):
            self.store.write(self.store.profiles_path, 'connections', [
                {'address': 'example.test', 'username': 'root', 'password': 'not-a-real-password'}])
        with self.assertRaises(ValueError):
            self.store.write(self.store.profiles_path, 'connections', [
                {'address': 'example.test', 'username': {'password': 'not-a-real-password'}}])
        with self.assertRaises(ValueError):
            self.store.remember_profile('https://root:not-a-real-password@example.test', 'root')
        self.assertNotIn('not-a-real-password', self.store.profiles_path.read_text(encoding='utf-8'))

    def test_unknown_profile_fields_are_not_loaded_or_rewritten(self):
        self.store.directory.mkdir()
        self.store.profiles_path.write_text(json.dumps({'version': 1, 'connections': [
            {'address': 'old.test', 'username': 'root', 'password': 'untrusted-extra-data'}]}), encoding='utf-8')
        self.assertEqual(self.store.profiles(), [])
        self.store.remember_profile('new.test', 'admin')
        self.assertNotIn('untrusted-extra-data', self.store.profiles_path.read_text(encoding='utf-8'))

    def test_profiles_can_be_forgotten_without_removing_certificate_trust(self):
        self.store.remember_profile('example.test', 'root')
        self.store.remember_profile('example.test', 'another-user')
        pin = ':'.join(['AA'] * 32)
        self.store.trust_certificate('example.test', pin)
        self.store.forget_profile('example.test', 'root')
        self.assertEqual(self.store.profiles(), [{'address':'example.test', 'username':'another-user'}])
        self.assertEqual(self.store.trusted_pin('example.test'), pin)
        self.store.forget_trust('example.test')
        self.assertIsNone(self.store.trusted_pin('example.test'))

    def test_trust_is_scoped_to_exact_endpoint_and_does_not_auto_accept_changes(self):
        pin = ':'.join(['AA'] * 32)
        self.store.trust_certificate('https://EXAMPLE.test:443/ui', pin)
        self.assertEqual(self.store.trusted_pin('example.test'), pin)
        self.assertIsNone(self.store.trusted_pin('example.test:8443'))
        self.assertIsNone(self.store.trusted_pin('another.test'))
        changed = ':'.join(['BB'] * 32)
        self.assertNotEqual(self.store.trusted_pin('example.test'), changed)
        data = json.loads(self.store.trust_path.read_text(encoding='utf-8'))
        self.assertEqual(data['version'],2)
        self.assertEqual(self.store.trusted_servers(),[{'address':'example.test','sha256':pin}])
        self.assertNotIn('example.test',self.store.trust_path.read_text(encoding='utf-8'))

    def test_failed_atomic_replace_preserves_previous_file(self):
        self.store.remember_profile('example.test', 'root')
        previous = self.store.profiles_path.read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('Simulated write failure')):
            with self.assertRaises(OSError):
                self.store.remember_profile('new.test', 'admin')
        self.assertEqual(self.store.profiles_path.read_bytes(), previous)
        self.assertEqual(list(self.store.directory.glob('*.tmp')), [])

    def test_clear_all_removes_both_settings_files_and_preserves_other_files(self):
        self.store.remember_profile('example.test','root')
        self.store.trust_certificate('example.test',':'.join(['AA']*32))
        other=self.store.directory/'unrelated.ova'
        other.write_bytes(b'unchanged')
        self.store.clear_all()
        self.assertFalse(self.store.profiles_path.exists())
        self.assertFalse(self.store.trust_path.exists())
        self.assertEqual(other.read_bytes(),b'unchanged')
        self.assertEqual(self.store.profiles(),[])
        self.assertIsNone(self.store.trusted_pin('example.test'))

    def test_clear_all_can_remove_corrupted_settings_without_parsing_them(self):
        self.store.directory.mkdir()
        for path in (self.store.profiles_path,self.store.trust_path):
            path.write_text('invalid settings',encoding='utf-8')
        self.store.clear_all()
        self.assertFalse(self.store.profiles_path.exists())
        self.assertFalse(self.store.trust_path.exists())

    def test_legacy_files_are_migrated_without_plaintext_backups(self):
        self.store.directory.mkdir()
        pin=':'.join(['AA']*32)
        self.store.profiles_path.write_text(json.dumps({'version':1,'connections':[
            {'address':'example.test','username':'root'}]}),encoding='utf-8')
        self.store.trust_path.write_text(json.dumps({'version':1,'servers':[
            {'address':'example.test','sha256':pin}]}),encoding='utf-8')
        self.assertEqual(set(self.store.migrate_legacy()),{'connections.json','trusted_servers.json'})
        self.assertEqual(self.store.profiles(),[{'address':'example.test','username':'root'}])
        self.assertEqual(self.store.trusted_pin('example.test'),pin)
        for path in self.store.directory.iterdir():
            self.assertNotIn('example.test',path.read_text(encoding='utf-8'))
            self.assertNotIn('"username"',path.read_text(encoding='utf-8'))
        self.assertEqual(self.store.migrate_legacy(),[])

    def test_encryption_failure_never_writes_a_plaintext_fallback(self):
        self.store.remember_profile('example.test','root')
        previous=self.store.profiles_path.read_bytes()
        with patch.object(self.store.protector,'protect',side_effect=OSError('Simulated DPAPI failure')):
            with self.assertRaises(OSError):
                self.store.remember_profile('new.test','admin')
        self.assertEqual(self.store.profiles_path.read_bytes(),previous)
        self.assertEqual(list(self.store.directory.glob('*.tmp')),[])

    def test_failed_roundtrip_preserves_legacy_file(self):
        self.store.directory.mkdir()
        previous=json.dumps({'version':1,'connections':[{'address':'example.test','username':'root'}]}).encode()
        self.store.profiles_path.write_bytes(previous)
        with patch.object(self.store.protector,'unprotect',return_value=b'wrong plaintext'):
            with self.assertRaisesRegex(OSError,'verification failed'):
                self.store.migrate_legacy()
        self.assertEqual(self.store.profiles_path.read_bytes(),previous)

    def test_wrong_account_or_corrupt_ciphertext_does_not_reset_saved_trust_silently(self):
        self.store.trust_certificate('example.test',':'.join(['AA']*32))
        previous=self.store.trust_path.read_bytes()
        with patch.object(self.store.protector,'unprotect',side_effect=OSError('Simulated wrong account')):
            with self.assertRaises(OSError):
                self.store.trusted_pin('example.test')
        self.assertEqual(self.store.trust_path.read_bytes(),previous)


if __name__ == '__main__':
    unittest.main(verbosity=2)
