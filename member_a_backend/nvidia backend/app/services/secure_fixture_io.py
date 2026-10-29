"""Handle-bound access to allowlisted synthetic text; no arbitrary path interface."""

import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from app.services.fixture_storage import FIXTURES, FixtureError, relative_path


def _identity(info):
    return info.st_dev, info.st_ino


def _regular(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise FixtureError("READ_PATH_UNSAFE")


@contextmanager
def _windows_file(root, parts):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("written", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    close = kernel.CloseHandle
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    information = kernel.GetFileInformationByHandle
    information.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    information.restype = wintypes.BOOL
    drive_type = kernel.GetDriveTypeW
    drive_type.argtypes, drive_type.restype = [wintypes.LPCWSTR], wintypes.UINT
    volume = kernel.GetVolumeInformationW
    volume.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    volume.restype = wintypes.BOOL
    filesystem = ctypes.create_unicode_buffer(32)
    if (
        drive_type(root.anchor) != 3
        or not volume(root.anchor, None, 0, None, None, None, filesystem, len(filesystem))
        or filesystem.value != "NTFS"
    ):
        raise FixtureError("READ_PLATFORM_UNSUPPORTED")

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.USHORT),
            ("maximum", wintypes.USHORT),
            ("buffer", ctypes.c_void_p),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.ULONG),
            ("root", wintypes.HANDLE),
            ("name", ctypes.POINTER(UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security", ctypes.c_void_p),
            ("quality", ctypes.c_void_p),
        ]

    class IoStatus(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

    create = ctypes.WinDLL("ntdll").NtCreateFile
    create.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatus),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    create.restype = wintypes.LONG

    def opened(parent, name, directory):
        encoded = name.encode("utf-16-le", errors="strict")
        if len(encoded) > 65532:
            raise FixtureError("READ_PATH_UNSAFE")
        buffer = ctypes.create_unicode_buffer(len(encoded) // 2 + 1)
        buffer.value = name
        string = UnicodeString(len(encoded), len(encoded) + 2, ctypes.cast(buffer, ctypes.c_void_p))
        attributes = ObjectAttributes(
            ctypes.sizeof(ObjectAttributes), parent, ctypes.pointer(string), 0x40, None, None
        )
        handle, status = wintypes.HANDLE(), IoStatus()
        # FILE_OPEN + OPEN_REPARSE_POINT, synchronous IO, read/traverse only; no write/delete share.
        code = create(
            ctypes.byref(handle),
            0x100080 | (0x20 if directory else 1),
            ctypes.byref(attributes),
            ctypes.byref(status),
            None,
            0,
            1,
            1,
            0x200000 | 0x20 | (1 if directory else 0x40),
            None,
            0,
        )
        if code != 0:
            if handle.value:
                close(handle)
            raise FixtureError("READ_PATH_UNSAFE")
        return handle.value

    def checked(handle, directory):
        info = FileInformation()
        if (
            not information(handle, ctypes.byref(info))
            or info.attributes & 0x400
            or (bool(info.attributes & 0x10) != directory)
            or (not directory and info.links != 1)
        ):
            raise FixtureError("READ_PATH_UNSAFE")

    with ExitStack() as stack:
        parent = opened(None, "\\??\\" + root.anchor, True)
        stack.callback(close, parent)
        checked(parent, True)
        directories = [parent]
        components = (*root.parts[1:], *parts)
        for index, component in enumerate(components):
            if any(c in component for c in ("/", "\\", ":", "\0")):
                raise FixtureError("READ_PATH_UNSAFE")
            directory = index < len(components) - 1
            handle = opened(parent, component, directory)
            try:
                checked(handle, directory)
                if directory:
                    stack.callback(close, handle)
                    parent = handle
                    directories.append(handle)
                else:
                    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                close(handle)
                raise
            if not directory:
                with os.fdopen(fd, "rb") as stream:
                    for held in directories:
                        checked(held, True)
                    yield stream
                    checked(msvcrt.get_osfhandle(stream.fileno()), False)
                    for held in directories:
                        checked(held, True)


@contextmanager
def _posix_file(root, parts):
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise FixtureError("READ_PLATFORM_UNSUPPORTED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        parent = os.open(root.anchor, flags)
        stack.callback(os.close, parent)
        edges = []
        components = (*root.parts[1:], *parts)
        for index, component in enumerate(components):
            directory = index < len(components) - 1
            fd = os.open(
                component,
                flags if directory else os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent,
            )
            opened = os.fstat(fd)
            edges.append((parent, component, _identity(opened), directory))
            if directory:
                stack.callback(os.close, fd)
                if not stat.S_ISDIR(opened.st_mode):
                    raise FixtureError("READ_PATH_UNSAFE")
                parent = fd
            else:
                with os.fdopen(fd, "rb") as stream:
                    _regular(opened)
                    yield stream
                    for parent_fd, name, identity, is_directory in edges:
                        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                        if _identity(current) != identity or (
                            not stat.S_ISDIR(current.st_mode)
                            if is_directory
                            else not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                        ):
                            raise FixtureError("READ_PATH_UNSAFE")


def _read_bounded(stream, limit):
    before = os.fstat(stream.fileno())
    _regular(before)
    if before.st_size > limit:
        raise FixtureError("READ_SIZE_LIMIT")
    content, count = [], 0
    while chunk := stream.read(min(8192, limit + 1 - count)):
        count += len(chunk)
        if count > limit:
            raise FixtureError("READ_SIZE_LIMIT")
        content.append(chunk)
    after = os.fstat(stream.fileno())
    _regular(after)
    if any(
        getattr(before, key) != getattr(after, key)
        for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
    ):
        raise FixtureError("READ_INTEGRITY_FAILURE")
    return b"".join(content)


def synthetic_bytes(root: Path, relative: str, limit: int) -> bytes:
    if relative not in {item[0] for item in FIXTURES.values()}:
        raise FixtureError("READ_PATH_UNSAFE")
    if not root.is_absolute() or ".." in root.parts or str(root).startswith(("\\\\", "//")):
        raise FixtureError("READ_PATH_UNSAFE")
    if type(limit) is not int or not 1 <= limit <= 65536:
        raise FixtureError("READ_SIZE_LIMIT")
    parts = relative_path(relative).parts
    if os.name not in ("nt", "posix"):
        raise FixtureError("READ_PLATFORM_UNSUPPORTED")
    opener = _windows_file if os.name == "nt" else _posix_file
    try:
        with opener(root, parts) as stream:
            return _read_bounded(stream, limit)
    except (OSError, ValueError, TypeError):
        raise FixtureError("READ_PATH_UNSAFE") from None
