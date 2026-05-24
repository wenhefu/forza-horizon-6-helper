"""Small Windows named-mutex guard to prevent duplicate helper instances."""
import ctypes


ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name="Local\\Forza6Helper"):
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = ctypes.c_bool
        self.handle = self._kernel32.CreateMutexW(None, True, name)
        self.acquired = bool(self.handle) and ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def close(self):
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()
