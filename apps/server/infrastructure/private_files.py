"""No-follow file opens on Linux and Windows; Windows is for client CI only."""

import os
import stat


def open_private(path, *, create=False):
    if os.name != "nt":
        return os.open(
            path, (os.O_WRONLY | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY) | os.O_NOFOLLOW, 0o600
        )
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)

    class Attributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", wintypes.LPVOID), ("inherit", wintypes.BOOL)]

    class Tag(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(Attributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        wintypes.LPVOID,
    ]
    descriptor = wintypes.LPVOID()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        "D:P(A;;FA;;;OW)(A;;FA;;;SY)", 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = Attributes(ctypes.sizeof(Attributes), descriptor, False)
    try:
        handle = kernel.CreateFileW(
            str(path),
            0xC0000000 if create else 0x80000000,
            1,
            ctypes.byref(attributes) if create else None,
            1 if create else 3,
            0x00200000,
            None,
        )
        error = ctypes.get_last_error()
    finally:
        kernel.LocalFree(descriptor)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(error)
    try:
        tag = Tag()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(tag), ctypes.sizeof(tag)):
            raise ctypes.WinError(ctypes.get_last_error())
        if tag.attributes & (stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_DIRECTORY):
            raise OSError("Private object cannot be a directory or reparse point")
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_WRONLY if create else os.O_RDONLY))
        handle = None  # fd now owns the native handle.
        return fd
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


def sync_directory(path):
    if os.name == "nt":
        # NTFS lacks POSIX directory fsync. Server deployment target remains Linux.
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_windows_acl(path):
    """Read the actual DACL for Windows privacy assertions (no POSIX mode emulation)."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = wintypes.LPVOID()
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        wintypes.LPVOID,
    ]
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    status = advapi.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, ctypes.byref(descriptor))
    if status:
        raise ctypes.WinError(status)
    result = wintypes.LPWSTR()
    try:
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 4, ctypes.byref(result), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value
    finally:
        if result:
            kernel.LocalFree(result)
        kernel.LocalFree(descriptor)
