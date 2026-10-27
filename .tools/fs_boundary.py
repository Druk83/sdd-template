#!/usr/bin/env python3
"""Source-only extension of the runtime filesystem safety primitives."""

from __future__ import annotations

import os

from sdd_runtime import fs_boundary as _runtime
from sdd_runtime.fs_boundary import *
from sdd_runtime.fs_boundary import (
    _absolute,
    _ensure_same_mount,
    _mount_signature,
    _windows_open,
)
if os.name == "nt":
    from sdd_runtime.fs_boundary import (
        _DELETE,
        _FILE_FLAG_BACKUP_SEMANTICS,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        _FILE_SHARE_READ,
        _FSCTL_SET_REPARSE_POINT,
        _GENERIC_READ,
        _INVALID_HANDLE,
        _IO_REPARSE_TAG_MOUNT_POINT,
        _OPEN_EXISTING,
        _FileAttributeTagInfo,
        _FileRenameInfo,
        _kernel32,
        _ntdll,
    )

def copy_file(
    source: Path, destination: Path, *, source_root: Path | None = None
) -> None:
    """Copy a regular file to a new destination without following links."""
    absolute_source = _absolute(source)
    boundary = _absolute(source_root or absolute_source.parent)
    try:
        absolute_source.relative_to(boundary)
    except ValueError as error:
        raise BoundaryError(f"Source is outside its filesystem boundary: {absolute_source}") from error
    with locked_directory(boundary) as (_, boundary_fd):
        root_signature = _mount_signature(boundary_fd)
    with open_regular(absolute_source) as source_stream:
        _ensure_same_mount(absolute_source, source_stream.fileno(), root_signature)
        mkdirs(destination.parent)
        with open_regular(destination, "wb", create_only=True) as destination_stream:
            for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                destination_stream.write(chunk)
            if os.name != "nt":
                os.fchmod(destination_stream.fileno(), stat.S_IMODE(os.fstat(source_stream.fileno()).st_mode))


def copy_tree(
    source: Path, destination: Path, *, source_root: Path | None = None
) -> None:
    """Copy a directory tree to a new destination without following links."""
    boundary = source_root or source
    directories, files = list_tree(source, boundary_root=boundary)
    mkdirs(destination.parent)
    mkdir_new(destination)
    for directory in directories:
        mkdirs(destination / directory.relative_to(source))
    for file in files:
        copy_file(file, destination / file.relative_to(source), source_root=boundary)


def remove_tree(root: Path) -> None:
    """Delete a directory tree through checked handles; reject links and special files."""
    list_tree(root)
    with locked_parent(root) as (absolute, parent_fd):
        if os.name == "nt":
            def dispose(handle: int) -> None:
                flag = ctypes.c_ubyte(1)
                if not _kernel32.SetFileInformationByHandle(handle, 4, ctypes.byref(flag), ctypes.sizeof(flag)):
                    raise ctypes.WinError(ctypes.get_last_error())

            def visit(path: Path) -> None:
                directory = _windows_open(path, directory=True, delete=True)
                try:
                    with os.scandir(path) as entries:
                        names = sorted(entry.name for entry in entries)
                    for name in names:
                        child = path / name
                        try:
                            file_handle = _windows_open(child, directory=False, delete=True)
                        except (PermissionError, BoundaryError):
                            visit(child)
                        else:
                            try:
                                dispose(file_handle)
                            finally:
                                _kernel32.CloseHandle(file_handle)
                    dispose(directory)
                finally:
                    _kernel32.CloseHandle(directory)

            visit(absolute)
        else:
            root_signature: tuple[int, int | None]

            def visit(descriptor: int, directory: Path) -> None:
                with os.scandir(descriptor) as entries:
                    names = sorted(entry.name for entry in entries)
                for name in names:
                    metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if stat.S_ISDIR(metadata.st_mode):
                        child = directory / name
                        child_fd = os.open(
                            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                        try:
                            _ensure_same_mount(child, child_fd, root_signature)
                            visit(child_fd, child)
                        finally:
                            os.close(child_fd)
                        os.rmdir(name, dir_fd=descriptor)
                    elif stat.S_ISREG(metadata.st_mode):
                        os.unlink(name, dir_fd=descriptor)
                    else:
                        raise BoundaryError(f"Link or unsupported file in deletion tree: {name}")

            root_fd = os.open(
                absolute.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                root_signature = _mount_signature(root_fd)
                visit(root_fd, absolute)
            finally:
                os.close(root_fd)
            os.rmdir(absolute.name, dir_fd=parent_fd)


def move_directory(source: Path, destination: Path) -> None:
    """Move an opened directory to a checked parent without replacing a target."""
    with locked_parent(source, share_write=True) as (source_path, source_parent):
        with locked_parent(destination, share_write=True, write_parent=True) as (target_path, target_parent):
            if os.name == "nt":
                handle = _windows_open(source_path, directory=True, delete=True)
                try:
                    name = target_path.name.encode("utf-16-le")
                    offset = _FileRenameInfo.FileName.offset
                    buffer = ctypes.create_string_buffer(max(ctypes.sizeof(_FileRenameInfo), offset + len(name) + 2))
                    info = ctypes.cast(buffer, ctypes.POINTER(_FileRenameInfo)).contents
                    info.ReplaceIfExists = 0
                    info.RootDirectory = target_parent
                    info.FileNameLength = len(name)
                    ctypes.memmove(ctypes.addressof(buffer) + offset, name, len(name))
                    io_status = (ctypes.c_void_p * 2)()
                    status = _ntdll.NtSetInformationFile(handle, io_status, buffer, len(buffer), 10)
                    if status < 0:
                        raise ctypes.WinError(_ntdll.RtlNtStatusToDosError(status))
                finally:
                    _kernel32.CloseHandle(handle)
            else:
                if sys.platform == "linux":
                    operation_name, no_replace = "renameat2", 1
                elif sys.platform == "darwin":
                    operation_name, no_replace = "renameatx_np", 4
                else:
                    raise BoundaryError("Exclusive directory rename is unsupported on this platform")
                libc = ctypes.CDLL(None, use_errno=True)
                operation = getattr(libc, operation_name, None)
                if operation is None:
                    raise BoundaryError(f"{operation_name} is unavailable")
                operation.argtypes = (
                    ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
                )
                operation.restype = ctypes.c_int
                result = operation(
                    source_parent, os.fsencode(source_path.name),
                    target_parent, os.fsencode(target_path.name), no_replace,
                )
                if result != 0:
                    error_number = ctypes.get_errno()
                    raise OSError(error_number, os.strerror(error_number), str(target_path))


def _alias_paths(alias: Path, target: Path) -> tuple[Path, Path]:
    alias_path, target_path = _absolute(alias), _absolute(target)
    if alias_path.parent != target_path.parent or alias_path == target_path:
        raise BoundaryError("Alias and target must be distinct siblings")
    return alias_path, target_path


def _windows_alias_handle(path: Path, *, delete: bool = False) -> int:
    handle = _kernel32.CreateFileW(
        str(path), _GENERIC_READ | (_DELETE if delete else 0), _FILE_SHARE_READ,
        None, _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS, None,
    )
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _FileAttributeTagInfo()
    if not _kernel32.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.WinError(ctypes.get_last_error())
        _kernel32.CloseHandle(handle)
        raise error
    if info.ReparseTag != _IO_REPARSE_TAG_MOUNT_POINT:
        _kernel32.CloseHandle(handle)
        raise BoundaryError(f"Expected a Windows junction: {path}")
    return handle


def _alias_target_matches(alias: Path, target: Path) -> bool:
    raw = os.readlink(alias)
    if os.name == "nt":
        if raw.startswith("\\\\?\\") or raw.startswith("\\??\\"):
            raw = raw[4:]
        return os.path.normcase(os.path.normpath(raw)) == os.path.normcase(str(target))
    return raw == target.name


def verify_directory_alias(alias: Path, target: Path) -> None:
    """Require a local alias to point to one exact sibling directory."""
    alias_path, target_path = _alias_paths(alias, target)
    with locked_directory(target_path):
        with locked_parent(alias_path) as (_, parent_fd):
            if os.name == "nt":
                handle = _windows_alias_handle(alias_path)
                try:
                    if not _alias_target_matches(alias_path, target_path):
                        raise BoundaryError(f"Junction target differs from expected release: {alias_path}")
                finally:
                    _kernel32.CloseHandle(handle)
            else:
                if not stat.S_ISLNK(os.stat(
                    alias_path.name, dir_fd=parent_fd, follow_symlinks=False,
                ).st_mode):
                    raise BoundaryError(f"Expected a symbolic link: {alias_path}")
                if os.readlink(alias_path.name, dir_fd=parent_fd) != target_path.name:
                    raise BoundaryError(f"Alias target differs from expected release: {alias_path}")


def create_directory_alias(alias: Path, target: Path) -> None:
    """Create a new versionless alias for a checked sibling directory."""
    alias_path, target_path = _alias_paths(alias, target)
    with locked_directory(target_path):
        with locked_parent(alias_path) as (_, parent_fd):
            if os.name == "nt":
                os.mkdir(alias_path)
                handle = _windows_open(alias_path, directory=True, write=True, delete=True)
                try:
                    substitute = ("\\??\\" + str(target_path)).encode("utf-16-le")
                    display = str(target_path).encode("utf-16-le")
                    names = substitute + b"\0\0" + display + b"\0\0"
                    data = struct.pack(
                        "<IHHHHHH", _IO_REPARSE_TAG_MOUNT_POINT, len(names) + 8,
                        0, 0, len(substitute), len(substitute) + 2, len(display),
                    ) + names
                    buffer = ctypes.create_string_buffer(data)
                    returned = wintypes.DWORD()
                    if not _kernel32.DeviceIoControl(
                        handle, _FSCTL_SET_REPARSE_POINT, buffer, len(data),
                        None, 0, ctypes.byref(returned), None,
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())
                except BaseException:
                    flag = ctypes.c_ubyte(1)
                    _kernel32.SetFileInformationByHandle(
                        handle, 4, ctypes.byref(flag), ctypes.sizeof(flag)
                    )
                    raise
                finally:
                    _kernel32.CloseHandle(handle)
            else:
                os.symlink(target_path.name, alias_path.name, dir_fd=parent_fd)
    verify_directory_alias(alias_path, target_path)


def remove_directory_alias(alias: Path, target: Path) -> None:
    """Remove the checked alias object without following or deleting its target."""
    alias_path, target_path = _alias_paths(alias, target)
    with locked_directory(target_path):
        with locked_parent(alias_path) as (_, parent_fd):
            if os.name == "nt":
                handle = _windows_alias_handle(alias_path, delete=True)
                try:
                    if not _alias_target_matches(alias_path, target_path):
                        raise BoundaryError(f"Junction target differs from expected release: {alias_path}")
                    flag = ctypes.c_ubyte(1)
                    if not _kernel32.SetFileInformationByHandle(
                        handle, 4, ctypes.byref(flag), ctypes.sizeof(flag)
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    _kernel32.CloseHandle(handle)
            else:
                if os.readlink(alias_path.name, dir_fd=parent_fd) != target_path.name:
                    raise BoundaryError(f"Alias target differs from expected release: {alias_path}")
                os.unlink(alias_path.name, dir_fd=parent_fd)
