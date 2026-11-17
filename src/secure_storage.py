"""Current-user settings encryption. No embedded key or plaintext fallback.

Windows uses DPAPI. macOS keeps a random 256-bit key in the user's login Keychain and
uses it for encrypt-then-MAC with HMAC-SHA256 (counter-mode keystream plus a tag).
"""
import ctypes
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import sys
from ctypes import wintypes


class DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDataProtection:
    def __init__(self):
        self.crypt32 = None
        self.kernel32 = None

    def load(self):
        if os.name != 'nt':
            raise OSError('Encrypted settings require Windows DPAPI; plaintext storage is disabled.')
        if self.crypt32 is not None:
            return
        # Restrict DLL resolution to Windows System32, not the app/work folder.
        crypt32 = ctypes.WinDLL('crypt32.dll', use_last_error=True, winmode=0x00000800)
        kernel32 = ctypes.WinDLL('kernel32.dll', use_last_error=True, winmode=0x00000800)
        crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR,
            ctypes.POINTER(DataBlob), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPVOID,
            ctypes.POINTER(DataBlob), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        self.crypt32, self.kernel32 = crypt32, kernel32

    @staticmethod
    def blob(data):
        buffer = ctypes.create_string_buffer(data, max(1, len(data)))
        return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    def transform(self, data, purpose, *, decrypt):
        self.load()
        if not isinstance(data, bytes) or not data or len(data) > 2_000_000:
            raise ValueError('Settings encryption expects nonempty bytes within the settings size limit.')
        source, source_buffer = self.blob(data)
        entropy, entropy_buffer = self.blob(b'OVA Exporter settings v2\0' + purpose.encode('ascii'))
        output = DataBlob()
        # CRYPTPROTECT_UI_FORBIDDEN only. Do not set LOCAL_MACHINE: settings
        # must be protected for the current Windows user, not every local user.
        flags = 0x1
        try:
            if decrypt:
                success = self.crypt32.CryptUnprotectData(ctypes.byref(source), None,
                    ctypes.byref(entropy), None, None, flags, ctypes.byref(output))
            else:
                success = self.crypt32.CryptProtectData(ctypes.byref(source), 'OVA Exporter settings',
                    ctypes.byref(entropy), None, None, flags, ctypes.byref(output))
            if not success:
                code = ctypes.get_last_error()
                operation = 'decryption' if decrypt else 'encryption'
                raise OSError(f'Windows DPAPI {operation} failed (error {code}). '
                              'Use the Windows account that saved the settings, or clear saved data.')
            if output.cbData > 2_000_000:
                raise ValueError('Unexpectedly large protected settings payload.')
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                if decrypt:
                    ctypes.memset(output.pbData, 0, output.cbData)
                self.kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
            # Keep both input buffers alive until the native call has returned.
            del source_buffer, entropy_buffer

    def protect(self, data, purpose):
        return self.transform(data, purpose, decrypt=False)

    def unprotect(self, data, purpose):
        return self.transform(data, purpose, decrypt=True)


class MacKeychainProtection:
    """Settings encryption on macOS, keyed by a secret stored in the login Keychain."""
    SECURITY = '/usr/bin/security'
    SERVICE = 'OVA Exporter GUI'
    ACCOUNT = 'settings-encryption-key'
    MAGIC = b'OVK1'
    NOT_FOUND = 44  # errSecItemNotFound, as returned by the security tool.

    def __init__(self, runner=None):
        self.run = runner or (lambda command: subprocess.run(  # nosec B603 - fixed system tool, no shell
            command, capture_output=True, text=True, timeout=20, check=False))
        self.key = None

    def read_key(self):
        result = self.run([self.SECURITY, 'find-generic-password', '-s', self.SERVICE, '-a', self.ACCOUNT, '-w'])
        if result.returncode == self.NOT_FOUND:
            return None
        value = (result.stdout or '').strip()
        if result.returncode != 0 or not re.fullmatch('[0-9a-f]{64}', value):
            raise OSError('The macOS Keychain did not provide the settings key. Unlock the login keychain, '
                          'or clear saved data in Settings.')
        return bytes.fromhex(value)

    def master_key(self):
        if self.key is None:
            key = self.read_key()
            if key is None:
                created = secrets.token_bytes(32)
                result = self.run([self.SECURITY, 'add-generic-password', '-s', self.SERVICE, '-a', self.ACCOUNT,
                                   '-l', 'OVA Exporter GUI settings', '-w', created.hex()])
                key = self.read_key()
                if result.returncode != 0 or key != created:
                    raise OSError('The settings key could not be saved in the macOS Keychain.')
            self.key = key
        return self.key

    def keys(self, purpose):
        master = self.master_key()
        label = b'OVA Exporter settings v2\0' + purpose.encode('ascii')
        return (hmac.new(master, b'encrypt\0' + label, hashlib.sha256).digest(),
                hmac.new(master, b'authenticate\0' + label, hashlib.sha256).digest())

    @staticmethod
    def keystream(key, nonce, length):
        blocks = (hmac.new(key, nonce + index.to_bytes(8, 'big'), hashlib.sha256).digest()
                  for index in range((length + 31) // 32))
        return b''.join(blocks)[:length]

    @staticmethod
    def check_size(data):
        if not isinstance(data, bytes) or not data or len(data) > 2_000_000:
            raise ValueError('Settings encryption expects nonempty bytes within the settings size limit.')

    def protect(self, data, purpose):
        self.check_size(data)
        encrypt, authenticate = self.keys(purpose)
        nonce = secrets.token_bytes(16)
        body = bytes(a ^ b for a, b in zip(data, self.keystream(encrypt, nonce, len(data))))
        tag = hmac.new(authenticate, self.MAGIC + nonce + body, hashlib.sha256).digest()
        return self.MAGIC + nonce + body + tag

    def unprotect(self, data, purpose):
        self.check_size(data)
        if len(data) < 4 + 16 + 1 + 32 or not data.startswith(self.MAGIC):
            raise OSError('Saved settings are not in the macOS format. Clear saved data in Settings.')
        encrypt, authenticate = self.keys(purpose)
        nonce, body, tag = data[4:20], data[20:-32], data[-32:]
        expected = hmac.new(authenticate, self.MAGIC + nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise OSError('Saved settings failed their integrity check. Clear saved data in Settings.')
        return bytes(a ^ b for a, b in zip(body, self.keystream(encrypt, nonce, len(body))))


def default_protector():
    return MacKeychainProtection() if sys.platform == 'darwin' else WindowsDataProtection()
