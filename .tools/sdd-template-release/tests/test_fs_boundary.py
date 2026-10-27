import os
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


TOOLS_ROOT = Path(__file__).resolve().parents[2]
TEST_TMP = TOOLS_ROOT.parent / "tmp"
sys.path.insert(0, str(TOOLS_ROOT))
sys.path.insert(0, str(TOOLS_ROOT / "sdd-template-release"))

import fs_boundary  # noqa: E402
import build_release  # noqa: E402


class BoundaryRaceTests(unittest.TestCase):
    def test_source_boundary_wrapper_imports_without_windows_symbols(self) -> None:
        runtime = types.ModuleType("sdd_runtime.fs_boundary")
        for name, value in vars(fs_boundary._runtime).items():
            if not name.startswith("_"):
                setattr(runtime, name, value)
        for name in ("_absolute", "_ensure_same_mount", "_mount_signature", "_windows_open"):
            setattr(runtime, name, getattr(fs_boundary._runtime, name))

        package = types.ModuleType("sdd_runtime")
        package.__path__ = []  # type: ignore[attr-defined]
        package.fs_boundary = runtime  # type: ignore[attr-defined]
        spec = importlib.util.spec_from_file_location(
            "fs_boundary_posix_probe", TOOLS_ROOT / "fs_boundary.py"
        )
        if spec is None:
            self.fail("Не удалось создать спецификацию source-only модуля.")
        loader = spec.loader
        if loader is None:
            self.fail("У source-only модуля отсутствует загрузчик.")
        module = importlib.util.module_from_spec(spec)
        with (
            patch.object(os, "name", "posix"),
            patch.dict(sys.modules, {"sdd_runtime": package, "sdd_runtime.fs_boundary": runtime}),
        ):
            loader.exec_module(module)

    def test_posix_guard_rejects_different_linux_mount_ids(self) -> None:
        path = Path("nested")
        with (
            patch.object(fs_boundary.os, "name", "posix"),
            patch.object(fs_boundary.sys, "platform", "linux"),
            patch.object(fs_boundary._runtime, "_mount_signature", return_value=(7, 12)),
        ):
            with self.assertRaises(fs_boundary.BoundaryError):
                fs_boundary._ensure_same_mount(path, 1, (7, 11))

    def test_final_symlink_does_not_read_or_write_external_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_bytes(b"preserve")
            link = root / "inside.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlinks unavailable: {error}")
            with self.assertRaises((OSError, fs_boundary.BoundaryError)):
                fs_boundary.read_bytes(link)
            with self.assertRaises((OSError, fs_boundary.BoundaryError)):
                fs_boundary.write_bytes(link, b"changed")
            self.assertEqual(outside.read_bytes(), b"preserve")

    def test_hard_link_cannot_read_copy_or_modify_external_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_bytes(b"preserve")
            project = root / "project"
            project.mkdir()
            linked = project / "content.txt"
            try:
                os.link(outside, linked)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Hard links unavailable: {error}")

            with self.assertRaises(fs_boundary.BoundaryError):
                fs_boundary.read_bytes(linked)
            with self.assertRaises(fs_boundary.BoundaryError):
                fs_boundary.write_bytes(linked, b"changed")
            with self.assertRaises(fs_boundary.BoundaryError):
                fs_boundary.replace_if_same(linked, b"preserve", b"changed")
            with self.assertRaises(fs_boundary.BoundaryError):
                fs_boundary.copy_file(linked, project / "copy.txt")
            self.assertEqual(outside.read_bytes(), b"preserve")

    @unittest.skipUnless(os.name == "nt", "Windows directory share mode")
    def test_parent_cannot_be_swapped_before_leaf_open(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            parent = root / "inside"
            parent.mkdir()
            file = parent / "content.txt"
            file.write_bytes(b"inside")
            renamed = root / "renamed"
            original_open = fs_boundary._windows_open
            attempted = False

            def open_with_swap(
                path: Path,
                *,
                directory: bool,
                write: bool = False,
                create: bool = False,
                delete: bool = False,
                readwrite: bool = False,
                share_write: bool = False,
            ) -> int:
                nonlocal attempted
                if path == file:
                    attempted = True
                    with self.assertRaises(OSError):
                        parent.rename(renamed)
                return original_open(
                    path,
                    directory=directory,
                    write=write,
                    create=create,
                    delete=delete,
                    readwrite=readwrite,
                    share_write=share_write,
                )

            with patch.object(fs_boundary._runtime, "_windows_open", side_effect=open_with_swap):
                self.assertEqual(fs_boundary.read_bytes(file), b"inside")
            self.assertTrue(attempted)
            self.assertTrue(parent.is_dir())
            self.assertFalse(renamed.exists())

    @unittest.skipIf(os.name == "nt", "POSIX dir_fd path binding")
    def test_posix_parent_swap_keeps_opened_directory(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            inside = root / "inside"
            inside.mkdir()
            (inside / "payload.txt").write_bytes(b"inside")
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "payload.txt"
            marker.write_bytes(b"private")
            original_open = fs_boundary.os.open
            swapped = False

            def open_after_swap(
                path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
            ) -> int:
                nonlocal swapped
                if path == "payload.txt" and dir_fd is not None and not swapped:
                    swapped = True
                    inside.rename(root / "renamed")
                    inside.symlink_to(outside, target_is_directory=True)
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with patch.object(fs_boundary.os, "open", side_effect=open_after_swap):
                self.assertEqual(fs_boundary.read_bytes(inside / "payload.txt"), b"inside")
            self.assertTrue(swapped)
            self.assertEqual(marker.read_bytes(), b"private")

    def test_delete_rejects_link_to_external_tree(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            managed = root / "managed"
            managed.mkdir()
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "marker.txt"
            marker.write_bytes(b"preserve")
            link = managed / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Directory symlinks unavailable: {error}")
            with self.assertRaises((OSError, fs_boundary.BoundaryError)):
                fs_boundary.remove_tree(managed)
            self.assertEqual(marker.read_bytes(), b"preserve")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mount-id boundary")
    def test_release_copy_rejects_nested_mount_before_copying(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "a.txt").write_bytes(b"inside")
            mounted = source / "z-mounted"
            mounted.mkdir()
            (mounted / "outside.txt").write_bytes(b"outside")
            target = root / "package"

            with patch.object(fs_boundary._runtime, "_mount_id", side_effect=[10, 10, 11]):
                with self.assertRaises(build_release.BuildError):
                    build_release.copy_tree(source, target, source_root=root)

            self.assertFalse(target.exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mount-id boundary")
    def test_remove_tree_checks_mounts_before_deleting_siblings(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "managed"
            root.mkdir()
            sibling = root / "a.txt"
            sibling.write_bytes(b"preserve")
            mounted = root / "z-mounted"
            mounted.mkdir()
            (mounted / "outside.txt").write_bytes(b"outside")

            with patch.object(fs_boundary._runtime, "_mount_id", side_effect=[10, 11]):
                with self.assertRaises(fs_boundary.BoundaryError):
                    fs_boundary.remove_tree(root)

            self.assertEqual(sibling.read_bytes(), b"preserve")
            self.assertTrue(mounted.is_dir())

    def test_move_uses_open_directory_and_preserves_existing_target(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "payload.txt").write_bytes(b"source")
            target = root / "target"
            target.mkdir()
            (target / "marker.txt").write_bytes(b"preserve")
            with self.assertRaises(OSError):
                fs_boundary.move_directory(source, target)
            self.assertEqual((source / "payload.txt").read_bytes(), b"source")
            self.assertEqual((target / "marker.txt").read_bytes(), b"preserve")

    def test_move_directory_succeeds_for_new_destination(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "payload.txt").write_bytes(b"source")
            target = root / "archive" / "source"
            target.parent.mkdir()
            fs_boundary.move_directory(source, target)
            self.assertFalse(source.exists())
            self.assertEqual((target / "payload.txt").read_bytes(), b"source")

    def test_directory_alias_points_only_to_expected_sibling(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            target = root / "sdd-template-1.9.6"
            target.mkdir()
            marker = target / "marker.txt"
            marker.write_bytes(b"preserve")
            alias = root / "sdd-template-current"
            fs_boundary.create_directory_alias(alias, target)
            fs_boundary.verify_directory_alias(alias, target)
            self.assertEqual((alias / "marker.txt").read_bytes(), b"preserve")
            other = root / "sdd-template-1.9.5"
            other.mkdir()
            with self.assertRaises((OSError, fs_boundary.BoundaryError)):
                fs_boundary.verify_directory_alias(alias, other)
            fs_boundary.remove_directory_alias(alias, target)
            self.assertFalse(alias.exists())
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_directory_alias_refuses_unknown_existing_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            target = root / "sdd-template-1.9.6"
            target.mkdir()
            alias = root / "sdd-template-current"
            alias.write_bytes(b"unknown")
            with self.assertRaises((OSError, fs_boundary.BoundaryError)):
                fs_boundary.create_directory_alias(alias, target)
            self.assertEqual(alias.read_bytes(), b"unknown")

    @unittest.skipUnless(os.name == "nt", "Windows directory share mode")
    def test_move_pins_both_parents_before_rename(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            source_parent = root / "source-parent"
            target_parent = root / "target-parent"
            source_parent.mkdir()
            target_parent.mkdir()
            source = source_parent / "release"
            source.mkdir()
            target = target_parent / "release"
            original_open = fs_boundary._windows_open
            attempted = False

            def open_with_swap(
                path: Path,
                *,
                directory: bool,
                write: bool = False,
                create: bool = False,
                delete: bool = False,
                readwrite: bool = False,
                share_write: bool = False,
            ) -> int:
                nonlocal attempted
                if path == source and delete:
                    attempted = True
                    with self.assertRaises(OSError):
                        source_parent.rename(root / "source-swapped")
                    with self.assertRaises(OSError):
                        target_parent.rename(root / "target-swapped")
                return original_open(
                    path,
                    directory=directory,
                    write=write,
                    create=create,
                    delete=delete,
                    readwrite=readwrite,
                    share_write=share_write,
                )

            with patch.object(fs_boundary, "_windows_open", side_effect=open_with_swap):
                fs_boundary.move_directory(source, target)
            self.assertTrue(attempted)
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
