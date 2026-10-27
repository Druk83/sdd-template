#!/usr/bin/env python3
"""Runtime file operations anchored to checked directory handles."""

from __future__ import annotations

import contextlib
import ctypes
import os
import stat
import struct
import sys
from pathlib import Path
from typing import BinaryIO, Generator, cast


class BoundaryError(OSError):
    """A path cannot be accessed without crossing an untrusted link."""


_POSIX_DIRFD_SUPPORTED = hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd


if os.name == "nt":
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    )
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.SetFileInformationByHandle.argtypes = (
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    )
    _kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    _ntdll.NtSetInformationFile.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.LPVOID, wintypes.ULONG, ctypes.c_int,
    )
    _ntdll.NtSetInformationFile.restype = wintypes.LONG
    _ntdll.RtlNtStatusToDosError.argtypes = (wintypes.LONG,)
    _ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
    _kernel32.DeviceIoControl.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    )
    _kernel32.DeviceIoControl.restype = wintypes.BOOL

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    class _FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", ctypes.c_wchar * 1),
        ]

    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _DELETE = 0x00010000
    _FILE_SHARE_READ = 0x1
    _FILE_SHARE_WRITE = 0x2
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_ATTRIBUTE_DIRECTORY = 0x10
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    _IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
    _FSCTL_SET_REPARSE_POINT = 0x000900A4


def _absolute(path: Path) -> Path:
    raw = Path(os.path.abspath(os.fspath(path)))
    if not raw.is_absolute():
        raise BoundaryError(f"Absolute path required: {path}")
    return raw


def _mount_id(descriptor: int) -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(f"/proc/self/fdinfo/{descriptor}", encoding="ascii") as info:
            for line in info:
                if line.startswith("mnt_id:"):
                    return int(line.partition(":")[2].strip())
    except (OSError, ValueError):
        return None
    return None


def _mount_signature(descriptor: int) -> tuple[int, int | None]:
    if os.name == "nt":
        return 0, None
    return os.fstat(descriptor).st_dev, _mount_id(descriptor)


def _ensure_same_mount(
    path: Path, descriptor: int, root_signature: tuple[int, int | None]
) -> None:
    if os.name == "nt":
        return
    device, mount_id = _mount_signature(descriptor)
    root_device, root_mount_id = root_signature
    if device != root_device:
        raise BoundaryError(f"Mount boundary in filesystem tree: {path}")
    if sys.platform.startswith("linux"):
        if root_mount_id is None or mount_id is None or mount_id != root_mount_id:
            raise BoundaryError(f"Mount boundary or unavailable mount metadata: {path}")
    elif os.path.ismount(path):
        raise BoundaryError(f"Mount boundary in filesystem tree: {path}")


def _windows_open(
    path: Path, *, directory: bool, write: bool = False, create: bool = False,
    delete: bool = False, readwrite: bool = False, share_write: bool = False
) -> int:
    access = (_GENERIC_READ | _GENERIC_WRITE if readwrite else _GENERIC_WRITE if write else _GENERIC_READ)
    access |= _DELETE if delete else 0
    share = _FILE_SHARE_READ | (_FILE_SHARE_WRITE if share_write else 0)
    flags = _FILE_FLAG_OPEN_REPARSE_POINT | (_FILE_FLAG_BACKUP_SEMANTICS if directory else 0)
    handle = _kernel32.CreateFileW(
        str(path), access, share, None, _CREATE_NEW if create else _OPEN_EXISTING, flags, None
    )
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _FileAttributeTagInfo()
    if not _kernel32.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.WinError(ctypes.get_last_error())
        _kernel32.CloseHandle(handle)
        raise error
    is_directory = bool(info.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY)
    if bool(info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT) or is_directory != directory:
        _kernel32.CloseHandle(handle)
        raise BoundaryError(f"Reparse point or unexpected file type: {path}")
    return handle


@contextlib.contextmanager
def locked_parent(
    path: Path, *, share_write: bool = False, write_parent: bool = False
) -> Generator[tuple[Path, int], None, None]:
    """Hold each parent directory while a child is opened or changed."""
    absolute = _absolute(path)
    parent = absolute.parent
    if parent == absolute:
        raise BoundaryError(f"A filesystem root is not a file: {absolute}")
    with contextlib.ExitStack() as stack:
        if os.name == "nt":
            current = Path(absolute.anchor)
            handle = _windows_open(current, directory=True, share_write=share_write and current == parent,
                                   write=write_parent and current == parent)
            stack.callback(_kernel32.CloseHandle, handle)
            for part in parent.parts[1:]:
                current /= part
                handle = _windows_open(current, directory=True, share_write=share_write and current == parent,
                                       write=write_parent and current == parent)
                stack.callback(_kernel32.CloseHandle, handle)
            yield absolute, handle
        else:
            if not _POSIX_DIRFD_SUPPORTED:
                raise BoundaryError("This platform does not support anchored file operations")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            handle = os.open(absolute.anchor, flags)
            stack.callback(os.close, handle)
            for part in parent.parts[1:]:
                handle = os.open(part, flags, dir_fd=handle)
                stack.callback(os.close, handle)
            yield absolute, handle


@contextlib.contextmanager
def open_regular(
    path: Path, mode: str = "rb", *, create_only: bool = False
) -> Generator[BinaryIO, None, None]:
    """Open a regular file without following a link at any path component."""
    if mode not in {"rb", "wb", "r+b"}:
        raise ValueError(f"Unsupported mode: {mode}")
    write = mode != "rb"
    readwrite = mode == "r+b"
    with locked_parent(path) as (absolute, parent_fd):
        if os.name == "nt":
            handle = _windows_open(absolute, directory=False, write=write, create=create_only, readwrite=readwrite)
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle, os.O_BINARY | (os.O_RDWR if readwrite else os.O_WRONLY if write else os.O_RDONLY)
                )
            except BaseException:
                _kernel32.CloseHandle(handle)
                raise
        else:
            flags = (os.O_RDWR if readwrite else os.O_WRONLY if write else os.O_RDONLY) | os.O_NOFOLLOW
            if create_only:
                flags |= os.O_CREAT | os.O_EXCL
            descriptor = os.open(absolute.name, flags, 0o666, dir_fd=parent_fd)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            raise BoundaryError(f"Not a regular file: {absolute}")
        if metadata.st_nlink != 1:
            os.close(descriptor)
            raise BoundaryError(f"Hard-linked file is outside the allowed boundary: {absolute}")
        with os.fdopen(descriptor, mode) as stream:
            if mode == "wb" and not create_only:
                stream.truncate(0)
            yield cast(BinaryIO, stream)


def read_bytes(path: Path) -> bytes:
    """Read a file through a checked handle."""
    with open_regular(path) as stream:
        return stream.read()


def write_bytes(path: Path, content: bytes, *, create_only: bool = False) -> None:
    """Write a file through a checked handle."""
    with open_regular(path, "wb", create_only=create_only) as stream:
        stream.write(content)


def replace_if_same(path: Path, expected: bytes, replacement: bytes) -> None:
    """Replace content only when the opened file still has the reviewed bytes."""
    with open_regular(path, "r+b") as stream:
        if stream.read() != expected:
            raise BoundaryError(f"File changed since review: {path}")
        stream.seek(0)
        stream.truncate(0)
        stream.write(replacement)


@contextlib.contextmanager
def locked_directory(path: Path) -> Generator[tuple[Path, int], None, None]:
    """Hold an existing directory and all its parents."""
    absolute = _absolute(path)
    if absolute == Path(absolute.anchor):
        if os.name == "nt":
            handle = _windows_open(absolute, directory=True)
            try:
                yield absolute, handle
            finally:
                _kernel32.CloseHandle(handle)
        else:
            handle = os.open(absolute, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                yield absolute, handle
            finally:
                os.close(handle)
        return
    with locked_parent(path) as (absolute, parent_fd):
        if os.name == "nt":
            handle = _windows_open(absolute, directory=True)
            try:
                yield absolute, handle
            finally:
                _kernel32.CloseHandle(handle)
        else:
            handle = os.open(
                absolute.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                yield absolute, handle
            finally:
                os.close(handle)


def mkdirs(path: Path) -> None:
    """Create missing directories one component at a time under open parents."""
    absolute = _absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        child = current / part
        with locked_directory(current) as (_, parent_fd):
            try:
                if os.name == "nt":
                    os.mkdir(child)
                else:
                    os.mkdir(part, dir_fd=parent_fd)
            except FileExistsError:
                pass
            with locked_directory(child):
                pass
        current = child


def mkdir_new(path: Path) -> None:
    """Create exactly one new directory under a checked parent."""
    with locked_parent(path) as (absolute, parent_fd):
        if os.name == "nt":
            os.mkdir(absolute)
        else:
            os.mkdir(absolute.name, dir_fd=parent_fd)


def list_tree(
    root: Path, *, boundary_root: Path | None = None
) -> tuple[list[Path], list[Path]]:
    """List directories and regular files without traversing links."""
    directories: list[Path] = []
    files: list[Path] = []
    absolute_root = _absolute(root)
    absolute_boundary = _absolute(boundary_root or root)
    with locked_directory(absolute_boundary) as (_, boundary_fd):
        root_signature = _mount_signature(boundary_fd)

    def visit(directory: Path) -> None:
        with locked_directory(directory) as (absolute, descriptor):
            if absolute != absolute_boundary:
                _ensure_same_mount(absolute, descriptor, root_signature)
            with os.scandir(absolute if os.name == "nt" else descriptor) as entries:
                names = sorted(entry.name for entry in entries)
            for name in names:
                child = absolute / name
                if os.name == "nt":
                    metadata = child.lstat()
                else:
                    metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                reparse = bool(
                    getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
                ) if os.name == "nt" else False
                if stat.S_ISLNK(metadata.st_mode) or reparse:
                    raise BoundaryError(f"Link in source tree: {child}")
                if stat.S_ISDIR(metadata.st_mode):
                    directories.append(child)
                    visit(child)
                elif stat.S_ISREG(metadata.st_mode):
                    files.append(child)
                else:
                    raise BoundaryError(f"Unsupported file type: {child}")

    visit(absolute_root)
    return directories, files


def list_children(root: Path) -> list[tuple[Path, str]]:
    """List immediate children while the containing directory is anchored."""
    children: list[tuple[Path, str]] = []
    with locked_directory(root) as (absolute, descriptor):
        with os.scandir(absolute if os.name == "nt" else descriptor) as entries:
            names = sorted(entry.name for entry in entries)
        for name in names:
            path = absolute / name
            metadata = (
                path.lstat() if os.name == "nt"
                else os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            )
            reparse = bool(
                getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
            ) if os.name == "nt" else False
            if stat.S_ISLNK(metadata.st_mode) or reparse:
                kind = "link"
            elif stat.S_ISDIR(metadata.st_mode):
                kind = "directory"
            elif stat.S_ISREG(metadata.st_mode):
                kind = "file"
            else:
                kind = "other"
            children.append((path, kind))
    return children


def list_files(root: Path) -> list[Path]:
    """List regular files without traversing symlinks or reparse points."""
    return list_tree(root)[1]

