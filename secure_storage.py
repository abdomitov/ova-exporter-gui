"""Windows current-user DPAPI encryption. No embedded key or plaintext fallback."""
import ctypes
import os
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
