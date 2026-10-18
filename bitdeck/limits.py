"""Windows Job Object resource limits. This is NOT an access-control sandbox."""
import ctypes
from ctypes import wintypes
import sys


class WindowsJob:
    def __init__(self, pid, memory_mb=768):
        self.handle = None
        if sys.platform != "win32":
            return
        SIZE_T = ctypes.c_size_t

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("minimum", SIZE_T), ("maximum", SIZE_T),
                        ("active", wintypes.DWORD), ("affinity", SIZE_T),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(key, ctypes.c_uint64) for key in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", SIZE_T),
                        ("job_memory", SIZE_T), ("peak_process", SIZE_T), ("peak_job", SIZE_T)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        self.kernel = k
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        # KILL_ON_JOB_CLOSE | PROCESS_MEMORY | ACTIVE_PROCESS | PROCESS_TIME
        info.basic.flags = 0x2000 | 0x100 | 0x8 | 0x2
        # Windows venv python.exe is a redirector that starts the base interpreter.
        # Both must fit in the same job. This cap is not an execution sandbox.
        info.basic.active = 2
        info.basic.process_time = 60 * 10_000_000
        info.process_memory = memory_mb * 1024 * 1024
        try:
            if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = k.OpenProcess(0x100 | 0x1, False, pid)  # SET_QUOTA | TERMINATE
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not k.AssignProcessToJobObject(self.handle, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                k.CloseHandle(process)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
