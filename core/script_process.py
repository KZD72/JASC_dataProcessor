"""OS process limits used before the script worker receives its start permit."""
from __future__ import annotations

import os


class ProcessLimits:
    def __init__(self, pid: int, memory_mb: int = 2048) -> None:
        self.handle = None
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong), ("flags", w.DWORD),
                        ("minimum", c.c_size_t), ("maximum", c.c_size_t), ("active", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(c.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                        ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]

        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [c.c_void_p, w.LPCWSTR], w.HANDLE
        kernel.SetInformationJobObject.argtypes, kernel.SetInformationJobObject.restype = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = [w.HANDLE, w.HANDLE], w.BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(c.get_last_error(), "Could not create the script resource limit job.")
        self.kernel, self.handle = kernel, handle
        settings = Extended()
        settings.basic.flags = 0x2000 | 0x100 | 0x8  # kill-on-close, process memory, one process
        settings.basic.active = 1
        settings.process_memory = memory_mb * 1024 * 1024
        try:
            if not kernel.SetInformationJobObject(handle, 9, c.byref(settings), c.sizeof(settings)):
                raise OSError(c.get_last_error(), "Could not set script process limits.")
            process = kernel.OpenProcess(0x100 | 0x1, False, pid)
            if not process:
                raise OSError(c.get_last_error(), "Could not open the script worker for resource limits.")
            try:
                if not kernel.AssignProcessToJobObject(handle, process):
                    raise OSError(c.get_last_error(), "Could not attach script process limits.")
            finally:
                kernel.CloseHandle(process)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def child_limits(memory_mb: int) -> None:
    if os.name == "posix":
        import resource
        size = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (size, size))
