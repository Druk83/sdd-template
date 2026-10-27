import hashlib
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = TOOL_ROOT.parents[1] / "tmp"
sys.path.insert(0, str(TOOL_ROOT))

import build_release  # noqa: E402
import install_framework  # noqa: E402


def file_record(path: Path, relative: str) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": relative,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def write_consumer_structure(target: Path, version: str) -> None:
    (target / ".project-structure.json").write_text(
        json.dumps(install_framework.consumer_project_structure(version)), encoding="utf-8"
    )


def write_consumer_manifest(package: Path, files: list[Path]) -> None:
    version = package.name.removeprefix("sdd-template-")
    manifest = {
        "package_id": "sdd-template",
        "version": version,
        "release_dir": f".agents/{package.name}",
        "files": [file_record(path, path.relative_to(package).as_posix()) for path in files],
    }
    (package / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def write_consumer_agents_template(source: Path, content: str = "# Consumer instructions\n") -> None:
    template = source / ".tools" / "sdd-template-release" / "templates" / "consumer-agents.md"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(content, encoding="utf-8")


class SourceLocationTests(unittest.TestCase):
    def test_external_source_clone_is_confined_to_unique_os_temp_workspace(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            os_temp = root / "os-temp"
            os_temp.mkdir()
            target = root / "consumer"
            target.mkdir()
            workspace = os_temp / ("sdd-template-update-" + "a" * 32)
            source = workspace / "sdd-template-source-1.9.6-12345678"
            source.mkdir(parents=True)
            with patch.object(install_framework.tempfile, "gettempdir", return_value=str(os_temp)):
                install_framework.validate_source_location(target, source)
                valid, relative = install_framework.validate_cleanup_target(target, source)
            self.assertEqual(valid, source)
            self.assertTrue(relative.startswith("OS-temp/"))

    def test_external_cleanup_removes_only_verified_clone(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            os_temp = root / "os-temp"
            os_temp.mkdir()
            target = root / "consumer"
            target.mkdir()
            workspace = os_temp / ("sdd-template-update-" + "b" * 32)
            source = workspace / "sdd-template-source-1.9.6-12345678"
            source.mkdir(parents=True)
            sibling = workspace / "keep.txt"
            sibling.write_text("preserve\n", encoding="utf-8")
            inventory = {"fingerprint": "verified", "source_fingerprint": "verified", "errors": [], "safe_to_delete": True}
            with patch.object(install_framework.tempfile, "gettempdir", return_value=str(os_temp)), patch.object(
                install_framework, "inventory_source_clone", return_value=inventory
            ):
                result = install_framework.cleanup_source_clone(target, source, "delete", "verified")
            self.assertEqual(result["status"], "deleted")
            self.assertFalse(source.exists())
            self.assertEqual(sibling.read_text(encoding="utf-8"), "preserve\n")

    def test_external_source_clone_rejects_non_unique_parent(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            os_temp = root / "os-temp"
            os_temp.mkdir()
            target = root / "consumer"
            target.mkdir()
            source = os_temp / "sdd-template-source-1.9.6-12345678"
            source.mkdir()
            with patch.object(install_framework.tempfile, "gettempdir", return_value=str(os_temp)):
                with self.assertRaises(build_release.BuildError):
                    install_framework.validate_source_location(target, source)


class SymlinkBoundaryTests(unittest.TestCase):
    def test_consumer_package_excludes_source_only_updater_code(self) -> None:
        source_root = build_release.repository_root()
        version = build_release.read_version(source_root)
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            stage = Path(temporary) / "package"
            build_release.build_stage(source_root, version, stage)
            self.assertFalse((stage / ".tools" / "fs_boundary.py").exists())
            self.assertFalse((stage / ".tools" / "sdd-template-release").exists())
            self.assertFalse((stage / ".manifest" / "exportmanifest.md").exists())
            self.assertFalse((stage / ".manifest" / "versionmanifest.md").exists())
            self.assertFalse((stage / ".manifest" / "README.md").exists())
            self.assertEqual(
                {path.name for path in (stage / ".manifest").glob("*.md")},
                build_release.CONSUMER_MANIFESTS,
            )
            self.assertTrue((stage / ".tools" / "sdd_runtime" / "fs_boundary.py").is_file())
            instructions = (stage / "sdd-template.instructions.md").read_text(encoding="utf-8")
            self.assertNotIn("release-registry.json", instructions)
            self.assertNotIn("install_framework.py", instructions)
            self.assertNotIn("--cleanup-action", instructions)
            build_release.validate_stage(stage, version)
            tools_root = stage / ".tools"
            smoke = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.path[:0] = sys.argv[1:4]; "
                    "from sdd_runtime import fs_boundary; import ui_reference, plantuml_render",
                    str(tools_root),
                    str(tools_root / "ui-reference"),
                    str(tools_root / "plantuml-render"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(smoke.returncode, 0, smoke.stderr)

    def test_release_validation_rejects_source_only_manifests(self) -> None:
        source_root = build_release.repository_root()
        version = build_release.read_version(source_root)
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            stage = Path(temporary) / "package"
            build_release.build_stage(source_root, version, stage)
            for name in build_release.SOURCE_ONLY_MANIFESTS:
                leaked = stage / ".manifest" / name
                leaked.parent.mkdir(parents=True, exist_ok=True)
                leaked.write_text("source-only\n", encoding="utf-8")
                with self.assertRaisesRegex(build_release.BuildError, "source-only"):
                    build_release.validate_stage(stage, version)
                leaked.unlink()

    def test_consumer_package_removes_internal_pdd_task_annotations(self) -> None:
        source_root = build_release.repository_root()
        version = build_release.read_version(source_root)
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            stage = Path(temporary) / "package"
            build_release.build_stage(source_root, version, stage)
            for relative, task_id in (
                (".tools/agent-logic/agent_logic/runtime_store.py", "IMPL-029"),
                (".tools/plantuml-render/bpmn-png-handler.mjs", "TD-025"),
            ):
                content = (stage / Path(relative)).read_text(encoding="utf-8")
                self.assertNotIn(f"@todo #{task_id}", content)
                self.assertNotIn("refs: .tasks/", content)

    def test_manifest_export_profile_rejects_unclassified_manifest(self) -> None:
        source_root = build_release.repository_root()
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            shutil.copytree(source_root / ".manifest", root / ".manifest")
            (root / ".manifest" / "newmanifest.md").write_text("unclassified\n", encoding="utf-8")
            with self.assertRaisesRegex(build_release.BuildError, "unclassified"):
                build_release.validate_manifest_export_profile(root)

    def test_release_copy_rejects_source_swap_after_precheck(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "asset.txt").write_bytes(b"inside")
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "asset.txt"
            marker.write_bytes(b"private")
            target = root / "target"
            original_list = build_release.fs_boundary.list_tree

            def list_after_swap(
                path: Path, *, boundary_root: Path | None = None
            ) -> tuple[list[Path], list[Path]]:
                if path == source:
                    source.rename(root / "moved")
                    try:
                        source.symlink_to(outside, target_is_directory=True)
                    except (OSError, NotImplementedError) as error:
                        self.skipTest(f"Directory symlinks unavailable: {error}")
                return original_list(path, boundary_root=boundary_root)

            with patch.object(build_release.fs_boundary, "list_tree", side_effect=list_after_swap):
                with self.assertRaises(build_release.BuildError):
                    build_release.copy_tree(source, target, source_root=source)
            self.assertEqual(marker.read_bytes(), b"private")
            self.assertFalse(target.exists())

    def make_symlink(self, target: Path, link: Path, *, is_directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=is_directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

    def test_release_copy_rejects_external_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            outside = base / "outside.txt"
            outside.write_text("private data", encoding="utf-8")
            self.make_symlink(outside, source / "leak.txt")
            target = base / "package"

            with self.assertRaises(build_release.BuildError):
                build_release.copy_tree(source, target, source_root=source)

            self.assertFalse((target / "leak.txt").exists())
            self.assertEqual(outside.read_text(encoding="utf-8"), "private data")

    def test_release_copy_file_rejects_external_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            outside = base / "outside.txt"
            outside.write_text("private data", encoding="utf-8")
            link = source / "required.txt"
            self.make_symlink(outside, link)

            with self.assertRaises(build_release.BuildError):
                build_release.copy_file(link, base / "package" / "required.txt", source_root=source)

            self.assertFalse((base / "package" / "required.txt").exists())

    def test_portable_registry_rejects_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            (source / ".tools").mkdir(parents=True)
            outside = base / "registry.json"
            outside.write_text('[{"name": "external"}]', encoding="utf-8")
            self.make_symlink(outside, source / ".tools" / "registry.json")

            with self.assertRaises(build_release.BuildError):
                build_release.portable_registry(source, "1.9.0")

    def test_path_guard_rejects_windows_reparse_point_metadata(self) -> None:
        path = Path("junction")
        metadata = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=metadata):
            self.assertTrue(build_release.is_link_or_reparse_point(path))

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_installed_release_rejects_windows_junction(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            agents = target / ".agents"
            agents.mkdir()
            outside = target / "outside"
            outside.mkdir()
            (outside / "preserve.txt").write_text("preserve", encoding="utf-8")
            junction = agents / "sdd-template-1.9.0"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"Windows junction unavailable: {created.stderr.strip()}")
            try:
                with self.assertRaises(build_release.BuildError):
                    install_framework.installed_release(target)
                self.assertEqual((outside / "preserve.txt").read_text(encoding="utf-8"), "preserve")
            finally:
                os.rmdir(junction)

    def create_resume_stage(self, root: Path, stage: Path) -> str:
        version = build_release.read_version(root)
        stage.mkdir(parents=True)
        (stage / "README.md").write_text("resume stage\n", encoding="utf-8")
        (stage / "sdd-template.instructions.md").write_text("instructions\n", encoding="utf-8")
        manifest = {
            "package_id": build_release.PACKAGE_ID,
            "version": version,
            "release_dir": f".agents/{build_release.release_name(version)}",
            "source_commit": build_release.git_value(root, ["rev-parse", "HEAD"], ""),
        }
        (stage / "release-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return version

    def test_resume_stage_outside_target_root_is_supported(self) -> None:
        root = build_release.repository_root()
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            output_root = base / "consumer"
            output_root.mkdir()
            stage = base / "source-clone" / "tmp" / "staging"
            version = self.create_resume_stage(root, stage)

            result = build_release.build_release(
                root,
                output_root,
                write=True,
                resume_stage=True,
                stage_root=stage,
                allow_existing_releases=True,
                allow_candidate=True,
            )

            package = output_root / ".agents" / build_release.release_name(version)
            self.assertEqual(result["status"], "written")
            self.assertFalse((package / ".tools" / "fs_boundary.py").exists())
            self.assertFalse((package / ".tools" / "sdd-template-release").exists())
            self.assertEqual((package / "README.md").read_text(encoding="utf-8"), "resume stage\n")

    def test_resume_stage_rejects_symlink_content_before_copy(self) -> None:
        root = build_release.repository_root()
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            output_root = base / "consumer"
            output_root.mkdir()
            stage = base / "source-clone" / "tmp" / "staging"
            version = self.create_resume_stage(root, stage)
            outside = base / "outside.txt"
            outside.write_text("private data", encoding="utf-8")
            self.make_symlink(outside, stage / "leak.txt")

            with self.assertRaises(build_release.BuildError):
                build_release.build_release(
                    root,
                    output_root,
                    write=True,
                    resume_stage=True,
                    stage_root=stage,
                    allow_existing_releases=True,
                    allow_candidate=True,
                )

            package = output_root / ".agents" / build_release.release_name(version)
            self.assertFalse(package.exists())
            self.assertEqual(outside.read_text(encoding="utf-8"), "private data")

    def test_resume_stage_rejects_symlink_parent_boundary(self) -> None:
        root = build_release.repository_root()
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            output_root = base / "consumer"
            output_root.mkdir()
            outside = base / "outside"
            stage = outside / "staging"
            version = self.create_resume_stage(root, stage)
            source_clone = base / "source-clone"
            source_clone.mkdir()
            self.make_symlink(outside, source_clone / "tmp", is_directory=True)

            with self.assertRaises(build_release.BuildError):
                build_release.build_release(
                    root,
                    output_root,
                    write=True,
                    resume_stage=True,
                    stage_root=source_clone / "tmp" / "staging",
                    allow_existing_releases=True,
                    allow_candidate=True,
                )

            package = output_root / ".agents" / build_release.release_name(version)
            self.assertFalse(package.exists())

    def test_installer_rejects_symlink_agents_destination(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            write_consumer_agents_template(source)
            outside = base / "outside.md"
            outside.write_text("user data\n", encoding="utf-8")
            self.make_symlink(outside, target / "AGENTS.md")

            with self.assertRaises(build_release.BuildError):
                install_framework.ensure_agents_instructions(target, source, "1.9.2")

            self.assertEqual(outside.read_text(encoding="utf-8"), "user data\n")

    def test_installer_rejects_symlink_parent_before_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            templates = source / ".tools" / "sdd-template-release" / "templates" / "project-root"
            templates.mkdir(parents=True)
            (templates / ".gitignore").write_text("tmp/\n", encoding="utf-8")
            for relative in install_framework.PROJECT_ROOT_TEMPLATES:
                template = templates / relative
                template.parent.mkdir(parents=True, exist_ok=True)
                template.write_text("template\n", encoding="utf-8")
            target = base / "target"
            target.mkdir()
            outside = base / "outside"
            outside.mkdir()
            self.make_symlink(outside, target / ".source", is_directory=True)

            with self.assertRaises(build_release.BuildError):
                install_framework.initialize_project_root(
                    target, target / ".agents" / "sdd-template-1.9.2", source, "1.9.2"
                )

            self.assertFalse((outside / "README.md").exists())


    def test_cleanup_rejects_symlink_tmp_before_following_it(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            target = base / "target"
            target.mkdir()
            outside = base / "user-data"
            source = outside / "sdd-template-source-1.9.1-12345678"
            source.mkdir(parents=True)
            (source / "important.txt").write_text("preserve", encoding="utf-8")
            self.make_symlink(outside, target / "tmp", is_directory=True)

            with self.assertRaises(build_release.BuildError):
                install_framework.validate_cleanup_target(
                    target, target / "tmp" / source.name
                )

            self.assertEqual((source / "important.txt").read_text(encoding="utf-8"), "preserve")


class SafetyInventoryTests(unittest.TestCase):
    def test_install_source_requires_clean_clone_and_matching_tag(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "README.md").write_text("framework\n", encoding="utf-8")
            entry = {"ref": "sdd-template-1.9.6", "ref_type": "tag", "tag": "sdd-template-1.9.6"}
            with patch.object(install_framework, "_git_status", return_value=(True, {"missing.md": "modified"}, None)):
                inventory = install_framework.inventory_source_clone(source)
            self.assertFalse(inventory["safe_to_delete"])
            errors = inventory.get("errors")
            assert isinstance(errors, list)
            self.assertTrue(any(isinstance(error, str) and "missing.md" in error for error in errors))
            with self.assertRaises(build_release.BuildError):
                install_framework.verify_install_source(source, entry, inventory)
            with patch.object(install_framework, "_git_status", return_value=(True, {}, None)), patch.object(
                install_framework.build_release, "git_value", return_value="a" * 40
            ):
                inventory = install_framework.inventory_source_clone(source)
            modified_inventory = {**inventory, "git": {"status_entries": {"README.md": "modified"}}}
            with self.assertRaises(build_release.BuildError):
                install_framework.verify_install_source(source, entry, modified_inventory)
            with patch.object(install_framework.build_release, "git_value", side_effect=["a" * 40, "b" * 40]):
                with self.assertRaises(build_release.BuildError):
                    install_framework.verify_install_source(source, entry, inventory)

    def test_use_older_release_migrates_link_to_selected_version(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.5-aaaaaaaa"
            source.mkdir(parents=True)
            (source / "README.md").write_text("source\n", encoding="utf-8")
            current = target / ".agents" / "sdd-template-1.9.6"
            current.mkdir(parents=True)
            current_readme = current / "README.md"
            current_readme.write_text("current\n", encoding="utf-8")
            write_consumer_manifest(current, [current_readme])
            write_consumer_structure(target, "1.9.6")
            alias = target / ".agents" / "sdd-template-current"
            install_framework.fs_boundary.create_directory_alias(alias, current)
            document = target / "AGENTS.md"
            original = "[Framework](.agents/sdd-template-current/README.md)\n"
            document.write_text(original, encoding="utf-8")
            old_fingerprint = install_framework.inventory_release(current)["fingerprint"]
            old = target / ".agents" / "sdd-template-1.9.5"

            def fake_build(*args: object, **kwargs: object) -> dict[str, object]:
                old.mkdir()
                readme = old / "README.md"
                readme.write_text("older\n", encoding="utf-8")
                write_consumer_manifest(old, [readme])
                return {"release_dir": ".agents/sdd-template-1.9.5", "status": "written"}

            def initialize(*args: object, **kwargs: object) -> dict[str, object]:
                write_consumer_structure(target, "1.9.5")
                return {"status": "updated"}

            common = [
                patch.object(install_framework.build_release, "read_release_registry", return_value={}),
                patch.object(install_framework.build_release, "release_entry", return_value={"ref": "ref-1.9.5", "ref_type": "tag", "tag": "ref-1.9.5", "install_path": ".agents/sdd-template-1.9.5"}),
                patch.object(install_framework.build_release, "read_version", return_value="1.9.5"),
                patch.object(install_framework.build_release, "git_value", return_value="a" * 40),
                patch.object(install_framework, "_git_status", return_value=(True, {}, None)),
                patch.object(install_framework, "inspect_agents_instructions", return_value={"conflicts": []}),
                patch.object(install_framework, "inspect_project_structure", return_value={"conflicts": []}),
                patch.object(install_framework, "initialize_project_root", side_effect=initialize),
                patch.object(install_framework, "ensure_agents_instructions", return_value={"status": "unchanged"}),
                patch.object(install_framework.build_release, "build_release", side_effect=fake_build),
            ]
            argv = [
                "install_framework.py", "--source-root", str(source),
                "--target-root", str(target), "--action", "use", "--version", "1.9.5",
                "--old-action", "delete", "--old-confirmation", str(old_fingerprint),
                "--cleanup-action", "keep", "--write",
            ]
            with contextlib.ExitStack() as stack:
                for operation in common:
                    stack.enter_context(operation)
                with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(install_framework.main(), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "completed")
            self.assertFalse(current.exists())
            self.assertTrue(old.exists())
            self.assertEqual(
                document.read_text(encoding="utf-8"),
                "[Framework](.agents/sdd-template-1.9.5/README.md)\n",
            )
            self.assertFalse(os.path.lexists(alias))
            self.assertFalse(os.path.lexists(alias))

    def test_old_release_change_after_confirmation_blocks_action(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            old = Path(temporary) / ".agents" / "sdd-template-1.9.5"
            old.mkdir(parents=True)
            readme = old / "README.md"
            readme.write_text("old\n", encoding="utf-8")
            write_consumer_manifest(old, [readme])
            fingerprint = install_framework.inventory_release(old)["fingerprint"]
            private = old / "private.txt"
            private.write_text("user data\n", encoding="utf-8")
            with self.assertRaises(build_release.BuildError):
                install_framework._verify_old_release_before_action(old, fingerprint)
            self.assertEqual(private.read_text(encoding="utf-8"), "user data\n")

    def test_update_resumes_after_pointer_change_before_alias_creation(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.6-aaaaaaaa"
            source.mkdir(parents=True)
            (source / "README.md").write_text("source\n", encoding="utf-8")
            old = target / ".agents" / "sdd-template-1.9.5"
            old.mkdir(parents=True)
            old_readme = old / "README.md"
            old_readme.write_text("old\n", encoding="utf-8")
            write_consumer_manifest(old, [old_readme])
            write_consumer_structure(target, "1.9.5")
            archived = target / ".tasks" / "done" / "TD.md"
            archived.parent.mkdir(parents=True)
            archived.write_text("[Old](../../.agents/sdd-template-1.9.5/README.md)\n", encoding="utf-8")
            new = target / ".agents" / "sdd-template-1.9.6"
            old_fingerprint = install_framework.inventory_release(old)["fingerprint"]

            def fake_build(*args: object, **kwargs: object) -> dict[str, object]:
                new.mkdir()
                readme = new / "README.md"
                readme.write_text("new\n", encoding="utf-8")
                write_consumer_manifest(new, [readme])
                return {"release_dir": ".agents/sdd-template-1.9.6", "status": "written"}

            def initialize(*args: object, **kwargs: object) -> dict[str, object]:
                write_consumer_structure(target, "1.9.6")
                return {"status": "updated"}

            common = [
                patch.object(
                    install_framework.build_release,
                    "read_release_registry",
                    return_value={"default_version": "1.9.6"},
                ),
                patch.object(install_framework.build_release, "release_entry", return_value={"ref": "ref-1.9.6", "ref_type": "tag", "tag": "ref-1.9.6", "install_path": ".agents/sdd-template-1.9.6"}),
                patch.object(install_framework.build_release, "read_version", return_value="1.9.6"),
                patch.object(install_framework.build_release, "git_value", return_value="a" * 40),
                patch.object(install_framework, "_git_status", return_value=(True, {}, None)),
                patch.object(install_framework, "inspect_agents_instructions", return_value={"conflicts": []}),
                patch.object(install_framework, "inspect_project_structure", return_value={"conflicts": []}),
                patch.object(install_framework, "initialize_project_root", side_effect=initialize),
                patch.object(install_framework.build_release, "build_release", side_effect=fake_build),
            ]
            argv = [
                "install_framework.py", "--source-root", str(source),
                "--target-root", str(target), "--action", "update",
                "--old-action", "delete", "--old-confirmation", str(old_fingerprint),
                "--cleanup-action", "keep", "--write",
            ]
            with contextlib.ExitStack() as stack:
                for operation in common:
                    stack.enter_context(operation)
                with patch.object(sys, "argv", argv[:-1]), redirect_stdout(io.StringIO()) as preflight_output:
                    self.assertEqual(install_framework.main(), 0)
                preflight = json.loads(preflight_output.getvalue())
                self.assertEqual(preflight["status"], "planned")
                self.assertEqual(len(preflight["historical_links"]), 1)
                with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as blocked_output:
                    self.assertEqual(install_framework.main(), 0)
                self.assertEqual(json.loads(blocked_output.getvalue())["status"], "awaiting_user_confirmation")
                self.assertFalse(new.exists())
                archived.unlink()
                with patch.object(install_framework, "ensure_agents_instructions", side_effect=RuntimeError("interrupted")):
                    with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(RuntimeError, "interrupted"):
                            install_framework.main()
                self.assertFalse(os.path.lexists(target / ".agents" / "sdd-template-current"))
                self.assertEqual(install_framework.installed_release(target), ("1.9.6", new))
                archived.write_text("[Old](../../.agents/sdd-template-1.9.5/README.md)\n", encoding="utf-8")
                with patch.object(install_framework, "ensure_agents_instructions", return_value={"status": "unchanged"}):
                    with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(install_framework.main(), 0)
                    blocked = json.loads(output.getvalue())
                    self.assertEqual(blocked["status"], "installed_pending_review")
                    self.assertEqual(blocked["next_action"]["type"], "resolve_historical_links")
                    self.assertTrue(old.exists())
                    archived.write_text(
                        "[Old](https://github.com/Druk83/sdd-template/blob/"
                        + "a" * 40 + "/README.md)\n", encoding="utf-8",
                    )
                    with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as resumed_output:
                        self.assertEqual(install_framework.main(), 0)
            result = json.loads(resumed_output.getvalue())
            self.assertEqual(result["status"], "completed")
            self.assertFalse(old.exists())
            self.assertTrue(source.exists())
            self.assertFalse(os.path.lexists(target / ".agents" / "sdd-template-current"))

    def test_full_update_uses_one_decision_and_finishes_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            commit = "a" * 40
            source = target / "tmp" / f"sdd-template-source-1.9.6-{commit[:8]}"
            source.mkdir(parents=True)
            (source / "README.md").write_text("source\n", encoding="utf-8")
            old = target / ".agents" / "sdd-template-1.9.5"
            old.mkdir(parents=True)
            old_readme = old / "README.md"
            old_readme.write_text("old\n", encoding="utf-8")
            old_template = old / ".requirements" / "template.md"
            old_template.parent.mkdir(parents=True)
            old_template.write_text("old template\n", encoding="utf-8")
            write_consumer_manifest(old, [old_readme, old_template])
            write_consumer_structure(target, "1.9.5")
            agents = target / "AGENTS.md"
            agents.write_text("Use .agents/sdd-template-1.9.5/README.md\n", encoding="utf-8")
            document = target / "docs" / "requirements" / "выбор.md"
            document.parent.mkdir(parents=True)
            document.write_text(
                "[template](../../.agents/sdd-template-1.9.5/.requirements/template.md)\n",
                encoding="utf-8",
            )
            new = target / ".agents" / "sdd-template-1.9.6"
            registry = {"default_version": "1.9.6"}
            entry = {"ref": "ref-1.9.6", "ref_type": "tag", "tag": "ref-1.9.6", "install_path": ".agents/sdd-template-1.9.6"}
            old_fingerprint = install_framework.inventory_release(old)["fingerprint"]

            def fake_build(*args: object, **kwargs: object) -> dict[str, object]:
                self.assertTrue(old.exists())
                new.mkdir()
                readme = new / "README.md"
                readme.write_text("new\n", encoding="utf-8")
                template = new / ".requirements" / "template.md"
                template.parent.mkdir()
                template.write_text("template\n", encoding="utf-8")
                write_consumer_manifest(new, [readme, template])
                return {"release_dir": ".agents/sdd-template-1.9.6", "status": "written"}

            def initialize(*args: object, **kwargs: object) -> dict[str, object]:
                write_consumer_structure(target, "1.9.6")
                return {"status": "updated"}

            common = [
                patch.object(install_framework.build_release, "read_release_registry", return_value=registry),
                patch.object(install_framework.build_release, "release_entry", return_value=entry),
                patch.object(install_framework.build_release, "read_version", return_value="1.9.6"),
                patch.object(install_framework.build_release, "git_value", return_value=commit),
                patch.object(install_framework, "_git_status", return_value=(True, {}, None)),
                patch.object(install_framework, "inspect_agents_instructions", return_value={"conflicts": []}),
                patch.object(install_framework, "inspect_project_structure", return_value={"conflicts": []}),
                patch.object(install_framework, "initialize_project_root", side_effect=initialize),
                patch.object(install_framework, "ensure_agents_instructions", return_value={"status": "unchanged"}),
                patch.object(install_framework.build_release, "build_release", side_effect=fake_build),
            ]
            with contextlib.ExitStack() as stack:
                for operation in common:
                    stack.enter_context(operation)
                base_args = [
                    "install_framework.py", "--source-root", str(source),
                    "--target-root", str(target), "--action", "update",
                ]
                with patch.object(sys, "argv", base_args), redirect_stdout(io.StringIO()) as first_output:
                    self.assertEqual(install_framework.main(), 0)
                first = json.loads(first_output.getvalue())
                self.assertEqual(first["status"], "planned")
                source_fingerprint = first["source_cleanup"]["source_fingerprint"]
                confirmed_args = base_args + [
                    "--old-action", "delete", "--old-confirmation", str(old_fingerprint),
                    "--cleanup-action", "delete", "--cleanup-fingerprint", source_fingerprint,
                    "--write",
                ]
                with patch.object(sys, "argv", confirmed_args), redirect_stdout(io.StringIO()) as second_output:
                    self.assertEqual(install_framework.main(), 0)
            final = json.loads(second_output.getvalue())
            self.assertEqual(final["status"], "completed")
            self.assertEqual(final["cleanup"]["status"], "deleted")
            self.assertFalse(source.exists())
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
            self.assertIn("sdd-template-1.9.6", document.read_text(encoding="utf-8"))
            self.assertNotIn("sdd-template-current", document.read_text(encoding="utf-8"))
            self.assertIn("FRAMEWORK_ROOT", agents.read_text(encoding="utf-8"))

    def test_clean_update_completes_in_one_write_invocation(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.6-12345678"
            source.mkdir(parents=True)
            (source / "README.md").write_text("source\n", encoding="utf-8")
            old = target / ".agents" / "sdd-template-1.9.5"
            old.mkdir(parents=True)
            old_readme = old / "README.md"
            old_readme.write_text("old\n", encoding="utf-8")
            write_consumer_manifest(old, [old_readme])
            write_consumer_structure(target, "1.9.5")
            new = target / ".agents" / "sdd-template-1.9.6"
            commit = "a" * 40

            def fake_build(*args: object, **kwargs: object) -> dict[str, object]:
                new.mkdir()
                new_readme = new / "README.md"
                new_readme.write_text("new\n", encoding="utf-8")
                write_consumer_manifest(new, [new_readme])
                return {"release_dir": ".agents/sdd-template-1.9.6", "status": "written"}

            def initialize(*args: object, **kwargs: object) -> dict[str, object]:
                write_consumer_structure(target, "1.9.6")
                return {"status": "updated"}

            review = {"status": "pass", "references": []}
            agents_review = {
                "conflicts": ["managed instructions differ"],
                "can_migrate": False,
                "can_replace_managed": True,
                "differences": [{"code": "managed_section_differs"}],
                "path_references": [],
            }
            structure_review = {
                "conflicts": ["framework.release_dir is stale"],
                "can_migrate": True,
            }
            argv = [
                "install_framework.py", "--source-root", str(source),
                "--target-root", str(target), "--action", "update", "--write",
            ]
            with (
                patch.object(install_framework.build_release, "read_release_registry", return_value={"default_version": "1.9.6"}),
                patch.object(install_framework.build_release, "release_entry", return_value={
                    "ref": "ref-1.9.6", "ref_type": "tag", "tag": "ref-1.9.6",
                    "install_path": ".agents/sdd-template-1.9.6",
                }),
                patch.object(install_framework.build_release, "read_version", return_value="1.9.6"),
                patch.object(install_framework.build_release, "git_value", return_value=commit),
                patch.object(install_framework, "validate_source_clone_name"),
                patch.object(install_framework, "_git_status", return_value=(True, {}, None)),
                patch.object(install_framework, "verify_install_source"),
                patch.object(install_framework, "inspect_agents_instructions", return_value=agents_review),
                patch.object(install_framework, "inspect_project_structure", return_value=structure_review),
                patch.object(install_framework, "initialize_project_root", side_effect=initialize) as initialize_mock,
                patch.object(install_framework, "ensure_agents_instructions", return_value={"status": "replaced"}) as agents_mock,
                patch.object(install_framework, "post_install_validate", return_value=review),
                patch.object(install_framework, "migrate_reviewed_references", return_value=(review, None)),
                patch.object(install_framework, "preserve_runtime_data", return_value={"status": "none"}),
                patch.object(install_framework, "_begin_alias_switch"),
                patch.object(install_framework, "_finish_alias_switch"),
                patch.object(install_framework.build_release, "build_release", side_effect=fake_build),
                patch.object(sys, "argv", argv),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(install_framework.main(), 0)

            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["cleanup"]["status"], "deleted")
            self.assertTrue(new.is_dir())
            self.assertFalse(old.exists())
            self.assertFalse(source.exists())
            structure = json.loads(
                (target / ".project-structure.json").read_text(encoding="utf-8")
            )
            self.assertEqual(structure["framework"]["release_dir"], ".agents/sdd-template-1.9.6")
            self.assertEqual(initialize_mock.call_args.args[-1], "migrate")
            self.assertEqual(agents_mock.call_args.args[-1], "replace-managed")

    def test_preflight_reports_all_known_update_conflicts_together(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            commit = "a" * 40
            source = target / "tmp" / f"sdd-template-source-1.9.6-{commit[:8]}"
            source.mkdir(parents=True)
            (source / "README.md").write_text("source\n", encoding="utf-8")
            old = target / ".agents" / "sdd-template-1.9.5"
            old.mkdir(parents=True)
            old_readme = old / "README.md"
            old_readme.write_text("old\n", encoding="utf-8")
            write_consumer_manifest(old, [old_readme])
            (old / "custom.txt").write_text("user data\n", encoding="utf-8")
            write_consumer_structure(target, "1.9.5")

            registry = {"default_version": "1.9.6"}
            entry = {
                "ref": "ref-1.9.6",
                "ref_type": "tag",
                "tag": "ref-1.9.6",
                "install_path": ".agents/sdd-template-1.9.6",
            }
            conflicts = ["test conflict"]
            source_inventory = {
                "source_fingerprint": "source-fingerprint",
                "safe_to_delete": False,
                "errors": ["unknown source file"],
            }
            argv = [
                "install_framework.py", "--source-root", str(source),
                "--target-root", str(target), "--action", "update",
                "--old-action", "delete", "--cleanup-action", "delete", "--write",
            ]

            with (
                patch.object(install_framework.build_release, "read_release_registry", return_value=registry),
                patch.object(install_framework.build_release, "release_entry", return_value=entry),
                patch.object(install_framework.build_release, "read_version", return_value="1.9.6"),
                patch.object(install_framework.build_release, "git_value", return_value=commit),
                patch.object(install_framework, "_git_status", return_value=(True, {}, None)),
                patch.object(install_framework, "inventory_source_clone", return_value=source_inventory),
                patch.object(install_framework, "post_install_validate", return_value={"status": "pass", "references": []}),
                patch.object(
                    install_framework,
                    "inspect_agents_instructions",
                    return_value={"status": "conflict", "conflicts": conflicts, "can_migrate": False},
                ),
                patch.object(
                    install_framework,
                    "inspect_project_structure",
                    return_value={"status": "conflict", "conflicts": conflicts, "can_migrate": False},
                ),
                patch.object(
                    install_framework.build_release,
                    "build_release",
                    side_effect=AssertionError("package build must wait for preflight decisions"),
                ) as build,
                patch.object(sys, "argv", argv),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(install_framework.main(), 0)

            plan = json.loads(output.getvalue())
            self.assertEqual(plan["status"], "awaiting_user_confirmation")
            self.assertEqual(plan["agents"]["conflicts"], conflicts)
            self.assertEqual(plan["project_structure"]["conflicts"], conflicts)
            self.assertEqual(
                plan["source_cleanup"]["source_fingerprint"],
                "source-fingerprint",
            )
            self.assertIn("old_release", plan)
            self.assertEqual(plan["next_action"]["type"], "user_confirmation")
            self.assertFalse((target / ".agents" / "sdd-template-1.9.6").exists())
            self.assertTrue((old / "custom.txt").exists())
            self.assertTrue(source.exists())
            build.assert_not_called()

    def test_cleanup_rejects_clone_swap_after_inventory(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            tmp_root = target / "tmp"
            tmp_root.mkdir()
            clone = tmp_root / "sdd-template-source-1.9.6-12345678"
            clone.mkdir()
            outside = target / "outside"
            outside.mkdir()
            marker = outside / "marker.txt"
            marker.write_bytes(b"preserve")

            def inventory_after_swap(_: Path) -> dict[str, object]:
                clone.rename(tmp_root / "moved")
                try:
                    clone.symlink_to(outside, target_is_directory=True)
                except (OSError, NotImplementedError) as error:
                    self.skipTest(f"Directory symlinks unavailable: {error}")
                return {"fingerprint": "known", "errors": []}

            with patch.object(install_framework, "inventory_source_clone", side_effect=inventory_after_swap):
                with self.assertRaises(OSError):
                    install_framework.cleanup_source_clone(target, clone, "delete", "known")
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_cleanup_command_blocks_delete_after_failed_post_install_review(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.2-12345678"
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            argv = [
                "install_framework.py", "--source-root", str(source),
                "--target-root", str(target), "--cleanup-action", "delete",
                "--cleanup-fingerprint", "confirmed-hash",
            ]
            with patch.object(sys, "argv", argv), patch.object(
                install_framework.build_release, "read_version", return_value="1.9.2"
            ), patch.object(
                install_framework, "installed_release", return_value=("1.9.2", package)
            ), patch.object(
                install_framework, "post_install_validate", return_value={"status": "blocked"}
            ), patch.object(install_framework, "cleanup_source_clone") as cleanup:
                with self.assertRaises(build_release.BuildError):
                    install_framework.main()
                cleanup.assert_not_called()

            with patch.object(sys, "argv", argv), patch.object(
                install_framework.build_release, "read_version", return_value="1.9.2"
            ), patch.object(
                install_framework, "installed_release", return_value=("1.9.2", package)
            ), patch.object(
                install_framework, "post_install_validate", return_value={"status": "pass"}
            ), patch.object(
                install_framework, "cleanup_source_clone", return_value={"status": "deleted"}
            ) as cleanup, redirect_stdout(io.StringIO()):
                self.assertEqual(install_framework.main(), 0)
                cleanup.assert_called_once_with(target, source, "delete", "confirmed-hash", "compact")

    def test_release_inventory_detects_figma_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            release = Path(temporary) / ".agents" / "sdd-template-1.9.0"
            release.mkdir(parents=True)
            readme = release / "README.md"
            readme.write_text("framework", encoding="utf-8")
            figma = release / ".figma" / "Samsung A51-A71"
            figma.mkdir(parents=True)
            (figma / "screen.html").write_text("user data", encoding="utf-8")
            manifest = {
                "schema_version": "1.0",
                "package_id": "sdd-template",
                "version": "1.9.0",
                "files": [file_record(readme, "README.md")],
            }
            (release / "release-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            inventory = cast(dict[str, Any], install_framework.inventory_release(release))

            self.assertFalse(inventory["safe_to_delete"])
            self.assertTrue(inventory["user_data_detected"])
            self.assertTrue(inventory["deletion_blocked"])
            self.assertEqual(inventory["top_level_nonstandard"], [".figma"])
            self.assertIn(".figma/Samsung A51-A71/screen.html", inventory["nonstandard_paths"])
            self.assertEqual(inventory["summary"]["user_data_entries"], 3)

    def test_cleanup_requires_fingerprint_and_detects_untracked_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            source.mkdir(parents=True)
            (source / "tracked.txt").write_text("framework", encoding="utf-8")
            (source / "custom.txt").write_text("user data", encoding="utf-8")

            with patch.object(
                install_framework,
                "_git_status",
                return_value=(True, {"custom.txt": "untracked"}, None),
            ):
                inventory = cast(dict[str, Any], install_framework.inventory_source_clone(source))
                self.assertIn("custom.txt", inventory["nonstandard_paths"])
                self.assertEqual(inventory["summary"]["statuses"]["untracked"], 1)

                plan = install_framework.cleanup_source_clone(target, source, "delete")
                self.assertEqual(plan["status"], "awaiting_user_confirmation")
                self.assertTrue(source.exists())


                result = cast(
                    dict[str, Any],
                    install_framework.cleanup_source_clone(
                        target,
                        source,
                        "delete",
                        inventory["fingerprint"],
                    ),
                )

            self.assertEqual(result["status"], "deleted")
            self.assertFalse(source.exists())

    def test_cleanup_rejects_changed_inventory(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            source.mkdir(parents=True)
            (source / "custom.txt").write_text("before", encoding="utf-8")
            with patch.object(
                install_framework,
                "_git_status",
                return_value=(True, {"custom.txt": "untracked"}, None),
            ):
                inventory = cast(dict[str, Any], install_framework.inventory_source_clone(source))
                (source / "custom.txt").write_text("after", encoding="utf-8")
                with self.assertRaises(build_release.BuildError):
                    install_framework.cleanup_source_clone(
                        target,
                        source,
                        "delete",
                        inventory["fingerprint"],
                    )
            self.assertTrue(source.exists())

    def test_one_preflight_confirmation_covers_generated_stage_only(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.6-12345678"
            source.mkdir(parents=True)
            (source / "tracked.txt").write_bytes(b"framework")
            with patch.object(install_framework, "_git_status", return_value=(True, {}, None)):
                before = install_framework.inventory_source_clone(source)
                self.assertTrue(before["safe_to_delete"])
                stage = source / "tmp" / "sdd-template-build-1.9.6"
                stage.mkdir(parents=True)
                generated = stage / "README.md"
                generated.write_bytes(b"generated")
                (stage / "release-manifest.json").write_text(
                    json.dumps({"files": [file_record(generated, "README.md")]}), encoding="utf-8"
                )
                after = install_framework.inventory_source_clone(source)
                self.assertEqual(before["source_fingerprint"], after["source_fingerprint"])
                self.assertTrue(after["safe_to_delete"])
                result = install_framework.settle_source_cleanup(
                    target, source, "delete", str(before["source_fingerprint"]), "compact"
                )
            self.assertEqual(result["status"], "deleted")
            self.assertFalse(source.exists())

    def test_one_preflight_confirmation_rejects_new_source_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.6-12345678"
            source.mkdir(parents=True)
            (source / "tracked.txt").write_bytes(b"framework")
            with patch.object(install_framework, "_git_status", return_value=(True, {}, None)):
                before = install_framework.inventory_source_clone(source)
                (source / "unknown.txt").write_bytes(b"user")
                result = install_framework.settle_source_cleanup(
                    target, source, "delete", str(before["source_fingerprint"]), "compact"
                )
            self.assertEqual(result["status"], "blocked")
            self.assertEqual((source / "unknown.txt").read_bytes(), b"user")

    def test_cleanup_inventory_separates_generated_staging_from_extra_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            stage = source / "tmp" / "sdd-template-build-1.9.1"
            stage.mkdir(parents=True)
            (source / ".git").mkdir()
            generated = stage / "README.md"
            generated.write_text("generated", encoding="utf-8")
            stage_manifest = {"files": [file_record(generated, "README.md")]}
            (stage / "release-manifest.json").write_text(
                json.dumps(stage_manifest),
                encoding="utf-8",
            )
            extra = stage / "custom.txt"
            extra.write_text("user data", encoding="utf-8")

            with patch.object(
                install_framework,
                "_git_status",
                return_value=(
                    True,
                    {
                        "tmp/": "ignored",
                        "tmp/sdd-template-build-1.9.1/custom.txt": "untracked",
                    },
                    None,
                ),
            ):
                inventory = cast(dict[str, Any], install_framework.inventory_source_clone(source))

            generated_entry = next(
                item for item in inventory["entries"] if item["path"] == "tmp/sdd-template-build-1.9.1/README.md"
            )
            self.assertEqual(generated_entry["classification"], "generated")
            self.assertIn("tmp/sdd-template-build-1.9.1/custom.txt", inventory["nonstandard_paths"])

    def test_cleanup_inventory_rejects_modified_staging_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            stage = source / "tmp" / "sdd-template-build-1.9.1"
            stage.mkdir(parents=True)
            generated = stage / "README.md"
            generated.write_text("original", encoding="utf-8")
            (stage / "release-manifest.json").write_text(
                json.dumps({"files": [file_record(generated, "README.md")]}), encoding="utf-8"
            )
            generated.write_text("changed", encoding="utf-8")

            with patch.object(install_framework, "_git_status", return_value=(True, {}, None)):
                inventory = cast(dict[str, Any], install_framework.inventory_source_clone(source))

            self.assertFalse(inventory["safe_to_delete"])
            self.assertIn("tmp/sdd-template-build-1.9.1/README.md", inventory["nonstandard_paths"])
            self.assertTrue(inventory["errors"])

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_cleanup_inventory_does_not_follow_windows_junction(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            source.mkdir(parents=True)
            outside = target / "outside"
            outside.mkdir()
            (outside / "preserve.txt").write_text("preserve", encoding="utf-8")
            junction = source / "mirror"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"Windows junction unavailable: {created.stderr.strip()}")
            try:
                with patch.object(install_framework, "_git_status", return_value=(True, {}, None)):
                    inventory = cast(dict[str, Any], install_framework.inventory_source_clone(source))
                self.assertFalse(inventory["safe_to_delete"])
                self.assertIn("mirror", inventory["nonstandard_paths"])
                self.assertNotIn("mirror/preserve.txt", {item["path"] for item in inventory["entries"]})
                with patch.object(install_framework, "_git_status", return_value=(True, {}, None)):
                    with self.assertRaises(build_release.BuildError):
                        install_framework.cleanup_source_clone(target, source, "delete", inventory["fingerprint"])
                self.assertEqual((outside / "preserve.txt").read_text(encoding="utf-8"), "preserve")
            finally:
                os.rmdir(junction)

    def test_build_can_stage_new_release_with_old_release_present_only_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            old_release = root / ".agents" / "sdd-template-1.9.0"
            old_release.mkdir(parents=True)
            target, existing = build_release.ensure_source_state(
                root,
                "1.9.1",
                allow_existing_releases=True,
            )
            self.assertEqual(target, root / ".agents" / "sdd-template-1.9.1")
            self.assertEqual(existing, [old_release])
            with self.assertRaises(build_release.BuildError):
                build_release.ensure_source_state(root, "1.9.1")

    def test_update_keeps_old_release_until_new_build_succeeds(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            source.mkdir(parents=True)
            old_release = target / ".agents" / "sdd-template-1.9.0"
            old_release.mkdir(parents=True)
            readme = old_release / "README.md"
            readme.write_text("old", encoding="utf-8")
            figma = old_release / ".figma" / "Samsung A51-A71"
            figma.mkdir(parents=True)
            (figma / "screen.html").write_text("user data", encoding="utf-8")
            manifest = {
                "files": [file_record(readme, "README.md")],
            }
            (old_release / "release-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            old_inventory = cast(dict[str, Any], install_framework.inventory_release(old_release))
            events: list[bool] = []

            def fake_build(*args: object, **kwargs: object) -> dict[str, object]:
                events.append(old_release.exists())
                new_release = target / ".agents" / "sdd-template-1.9.1"
                new_release.mkdir(parents=True)
                return {"release_dir": ".agents/sdd-template-1.9.1"}

            registry = {"default_version": "1.9.1"}
            entry = {
                "ref": "sdd-template-1.9.1",
                "install_path": ".agents/sdd-template-1.9.1",
            }
            argv = [
                "install_framework.py",
                "--source-root",
                str(source),
                "--target-root",
                str(target),
                "--action",
                "update",
                "--old-action",
                "delete",
                "--write",
            ]
            with patch.object(sys, "argv", argv), patch.object(
                install_framework.build_release,
                "read_release_registry",
                return_value=registry,
            ), patch.object(
                install_framework.build_release,
                "release_entry",
                return_value=entry,
            ), patch.object(
                install_framework.build_release,
                "read_version",
                return_value="1.9.1",
            ), patch.object(
                install_framework,
                "validate_source_clone_name",
            ), patch.object(
                install_framework,
                "inspect_agents_instructions",
                return_value={"conflicts": []},
            ), patch.object(
                install_framework,
                "inspect_project_structure",
                return_value={"conflicts": []},
            ):
                first_output = io.StringIO()
                first_error = io.StringIO()
                with redirect_stdout(first_output), redirect_stderr(first_error):
                    install_framework.main()
            self.assertTrue(old_release.exists())
            self.assertIn(".figma", first_output.getvalue())
            self.assertIn("source_cleanup", first_output.getvalue())
            self.assertEqual(first_error.getvalue(), "")

            argv.extend(["--old-confirmation", str(old_inventory["fingerprint"])])
            with patch.object(sys, "argv", argv), patch.object(
                install_framework.build_release,
                "read_release_registry",
                return_value=registry,
            ), patch.object(
                install_framework.build_release,
                "release_entry",
                return_value=entry,
            ), patch.object(
                install_framework.build_release,
                "read_version",
                return_value="1.9.1",
            ), patch.object(
                install_framework,
                "validate_source_clone_name",
            ), patch.object(
                install_framework,
                "inspect_agents_instructions",
                return_value={"conflicts": []},
            ), patch.object(
                install_framework,
                "inspect_project_structure",
                return_value={"conflicts": []},
            ), patch.object(
                install_framework,
                "initialize_project_root",
                return_value={},
            ), patch.object(
                install_framework,
                "ensure_agents_instructions",
                return_value={"conflicts": []},
            ), patch.object(
                install_framework,
                "post_install_validate",
                return_value={"status": "pass"},
            ), patch.object(
                install_framework,
                "verify_install_source",
            ), patch.object(
                install_framework.build_release,
                "build_release",
                side_effect=fake_build,
            ), patch.object(
                install_framework,
                "cleanup_plan",
                return_value={"inventory": {}, "next_action": {}},
            ):
                second_output = io.StringIO()
                second_error = io.StringIO()
                with redirect_stdout(second_output), redirect_stderr(second_error):
                    install_framework.main()

            self.assertEqual(events, [True])
            self.assertFalse(old_release.exists())
            self.assertTrue((target / ".agents" / "sdd-template-1.9.1").exists())
            self.assertEqual(second_error.getvalue(), "")


class FrameworkPathMigrationTests(unittest.TestCase):
    def test_consumer_structure_has_one_versioned_release_pointer(self) -> None:
        structure = cast(dict[str, Any], install_framework.consumer_project_structure("1.9.2"))
        serialized = json.dumps(structure, ensure_ascii=False)
        self.assertEqual(serialized.count("sdd-template-1.9.2"), 1)
        self.assertEqual(structure["framework"]["release_dir"], ".agents/sdd-template-1.9.2")

    def test_smartnormtimer_structure_migrates_derived_fields_once(self) -> None:
        structure = {
            "framework": {
                "package_id": "sdd-template",
                "release_dir": ".agents/sdd-template-1.9.4",
                "tools_registry": ".agents/sdd-template-1.9.4/.tools/registry.json",
                "chatlog_dir": ".agents/sdd-template-1.9.4/.chatlog",
            },
            "folders": [{"name": "tools", "path": "tools"}],
            "custom": {"tools_registry": "project/tools.json"},
        }
        migrated, changes = install_framework.migrate_project_structure(structure, "1.9.5")
        migrated = cast(dict[str, Any], migrated)
        self.assertEqual(migrated["framework"], {
            "package_id": "sdd-template", "release_dir": ".agents/sdd-template-1.9.5"
        })
        self.assertEqual(migrated["folders"], structure["folders"])
        self.assertEqual(migrated["custom"], structure["custom"])
        self.assertEqual(json.dumps(migrated).count("sdd-template-1.9.5"), 1)
        self.assertIn("/framework/tools_registry", {change["json_path"] for change in changes})
        self.assertIn("/framework/chatlog_dir", {change["json_path"] for change in changes})
        self.assertEqual(install_framework.migrate_project_structure(migrated, "1.9.5")[1], [])

    def test_external_framework_release_pointer_blocks_migration(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "source"
            source.mkdir()
            structure = {"framework": {"package_id": "sdd-template", "release_dir": "C:/outside/release"}}
            destination = target / ".project-structure.json"
            destination.write_text(json.dumps(structure), encoding="utf-8")
            review = cast(dict[str, Any], install_framework.inspect_project_structure(target, source, "1.9.5"))
            self.assertEqual(review["status"], "conflict")
            self.assertFalse(review["can_migrate"])
            self.assertEqual(review["references"][0]["classification"], "ambiguous")
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), structure)

    def test_replace_action_rejects_clear_structure_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "source"
            source.mkdir()
            destination = target / ".project-structure.json"
            original = json.dumps({"project": {"name": "preserve me"}})
            destination.write_text(original, encoding="utf-8")

            with patch.object(
                install_framework,
                "inspect_project_structure",
                return_value={"status": "clear", "conflicts": [], "can_replace": False},
            ):
                with self.assertRaises(build_release.BuildError):
                    install_framework.ensure_project_structure(target, source, "1.9.5", "replace")

            self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_custom_folder_reference_is_not_rewritten_as_framework_owned(self) -> None:
        structure = {
            "framework": {"package_id": "sdd-template", "release_dir": ".agents/sdd-template-1.9.4"},
            "folders": [{"name": "Archived source", "path": ".agents/sdd-template-1.9.4/.source"}],
        }
        migrated, _ = install_framework.migrate_project_structure(structure, "1.9.5")
        migrated = cast(dict[str, Any], migrated)
        self.assertEqual(migrated["folders"], structure["folders"])

    def test_structure_migration_passes_post_install_gate(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "source"
            source.mkdir()
            package = target / ".agents" / "sdd-template-1.9.5"
            (package / ".tools").mkdir(parents=True)
            (package / ".chatlog").mkdir()
            files = [package / "README.md", package / ".tools" / "registry.json", package / ".chatlog" / ".gitkeep"]
            for path in files:
                path.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, files)
            structure = {
                "framework": {
                    "package_id": "sdd-template",
                    "release_dir": ".agents/sdd-template-1.9.4",
                    "tools_registry": ".agents/sdd-template-1.9.4/.tools/registry.json",
                    "chatlog_dir": ".agents/sdd-template-1.9.4/.chatlog",
                }
            }
            (target / ".project-structure.json").write_text(json.dumps(structure), encoding="utf-8")
            migration = install_framework.ensure_project_structure(target, source, "1.9.5", "migrate")
            self.assertEqual(migration["status"], "migrated")
            review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.5", package))
            self.assertEqual(review["status"], "pass")
            self.assertEqual(review["summary"]["stale"], 0)

    def test_project_structure_migrate_preserves_project_fields(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "source"
            source.mkdir()
            structure = {
                "version": "1.0",
                "framework_root": ".agents/sdd-template-1.9.1",
                "framework": {
                    "release_dir": ".agents/sdd-template-1.9.1",
                    "tools_registry": ".agents/sdd-template-1.9.1/.tools/registry.json",
                    "chatlog_dir": ".agents/sdd-template-1.9.1/.chatlog",
                },
                "folders": [
                    {"name": "SDD Framework", "path": ".manifest"},
                    {"name": "Project source", "path": ".source"},
                ],
                "tools": {"registry_path": ".tools/registry.json"},
                "templates": {"task_template": ".requirements/task.md"},
                "custom": {
                    "owner": "project",
                    "path": "docs/requirements",
                    "release_dir": "docs/releases",
                    "tools_registry": "project/tools.json",
                    "chatlog_dir": "project/logs",
                },
            }
            destination = target / ".project-structure.json"
            destination.write_text(json.dumps(structure, ensure_ascii=False), encoding="utf-8")

            review = cast(
                dict[str, Any],
                install_framework.inspect_project_structure(target, source, "1.9.2"),
            )
            self.assertEqual(review["status"], "conflict")
            self.assertTrue(review["can_migrate"])
            self.assertGreaterEqual(len(review["migration_changes"]), 4)

            result = cast(
                dict[str, Any],
                install_framework.ensure_project_structure(target, source, "1.9.2", "migrate"),
            )
            self.assertEqual(result["status"], "migrated")
            migrated = json.loads(destination.read_text(encoding="utf-8"))
            self.assertNotIn("framework_root", migrated)
            self.assertEqual(migrated["framework"]["release_dir"], ".agents/sdd-template-1.9.2")
            self.assertNotIn("tools_registry", migrated["framework"])
            self.assertNotIn("chatlog_dir", migrated["framework"])
            self.assertNotIn("registry_path", migrated["tools"])
            self.assertNotIn("task_template", migrated["templates"])
            self.assertEqual(migrated["folders"][1]["path"], ".source")
            self.assertEqual(migrated["custom"], structure["custom"])
            repeated, repeated_changes = install_framework.migrate_project_structure(migrated, "1.9.2")
            self.assertEqual(repeated, migrated)
            self.assertEqual(repeated_changes, [])

    def test_project_structure_migrate_blocks_ambiguous_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            source = target / "source"
            source.mkdir()
            original = {"note": "Пользовательская ссылка: .manifest/taskmanifest.md"}
            destination = target / ".project-structure.json"
            destination.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            result = cast(
                dict[str, Any],
                install_framework.ensure_project_structure(target, source, "1.9.2", "migrate"),
            )
            self.assertEqual(result["status"], "awaiting_user_confirmation")
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), original)

    def test_agents_migrate_replaces_only_managed_block(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            write_consumer_agents_template(source, "# Current framework instructions\n")
            target = base / "target"
            target.mkdir()
            old_block = (
                f"{install_framework.AGENTS_MANAGED_BEGIN}\n"
                "See .agents/sdd-template-1.9.1/.manifest/taskmanifest.md\n"
                f"{install_framework.AGENTS_MANAGED_END}\n"
            )
            agents = target / "AGENTS.md"
            agents.write_text("# User instructions\n\n" + old_block, encoding="utf-8")

            review = cast(
                dict[str, Any],
                install_framework.inspect_agents_instructions(target, source, "1.9.2"),
            )
            self.assertTrue(review["can_migrate"])
            result = cast(
                dict[str, Any],
                install_framework.ensure_agents_instructions(target, source, "1.9.2", "migrate"),
            )
            content = agents.read_text(encoding="utf-8")
            self.assertEqual(result["status"], "replaced")
            self.assertIn("# User instructions", content)
            self.assertIn("# Current framework instructions", content)
            self.assertNotIn("sdd-template-1.9.1", content)

    def test_agents_migrate_blocks_mixed_legacy_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            write_consumer_agents_template(source, "# Current framework instructions\n")
            target = base / "target"
            target.mkdir()
            agents = target / "AGENTS.md"
            original = "# User instructions\nSee .manifest/taskmanifest.md\n"
            agents.write_text(original, encoding="utf-8")

            review = cast(
                dict[str, Any],
                install_framework.inspect_agents_instructions(target, source, "1.9.2"),
            )
            self.assertEqual(review["status"], "conflict")
            self.assertFalse(review["can_migrate"])
            result = cast(
                dict[str, Any],
                install_framework.ensure_agents_instructions(target, source, "1.9.2", "migrate"),
            )
            self.assertEqual(result["status"], "awaiting_user_confirmation")
            self.assertEqual(agents.read_text(encoding="utf-8"), original)


class PostInstallValidationTests(unittest.TestCase):
    def test_consumer_agents_template_is_runtime_only_and_passes_link_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary) / "project"
            target.mkdir()
            version = build_release.read_version(build_release.repository_root())
            write_consumer_structure(target, version)
            package = target / ".agents" / f"sdd-template-{version}"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            agents = target / "AGENTS.md"
            agents.write_text(
                install_framework.agents_managed_block(build_release.repository_root()),
                encoding="utf-8",
            )

            content = agents.read_text(encoding="utf-8")
            self.assertIn("FRAMEWORK_ROOT", content)
            self.assertNotIn("sdd-template-release", content)
            self.assertEqual(install_framework._framework_path_matches(content), [])
            result = install_framework.post_install_validate(target, version, package)
            self.assertEqual(result["status"], "pass", result)

    def test_reference_validation_cache_skips_unchanged_document_scan(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            target = root / "project"
            target.mkdir()
            cache_path = root / "reference-validation.json"
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            agents = target / "AGENTS.md"
            agents.write_text(".agents/sdd-template-1.9.2/README.md\n", encoding="utf-8")

            with patch.object(
                install_framework,
                "_reference_validation_cache_path",
                return_value=cache_path,
            ), patch.object(
                install_framework,
                "_post_install_reference_records",
                wraps=install_framework._post_install_reference_records,
            ) as scan:
                first = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
                first_scan_count = scan.call_count
                self.assertEqual(first["status"], "pass")
                self.assertGreater(first_scan_count, 0)

                second = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
                self.assertEqual(second["status"], "pass")
                self.assertTrue(
                    second.get("reference_scan_cached"),
                    f"cache={cache_path.read_text(encoding='utf-8') if cache_path.exists() else 'missing'}; result={second!r}",
                )
                self.assertEqual(scan.call_count, first_scan_count)

                agents.write_text(agents.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
                third = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
                self.assertEqual(third["status"], "pass")
                self.assertNotIn("reference_scan_cached", third)
                self.assertGreater(scan.call_count, first_scan_count)

                second_scan_count = scan.call_count
                cache_path.write_text("{invalid", encoding="utf-8")
                fourth = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
                self.assertEqual(fourth["status"], "pass")
                self.assertNotIn("reference_scan_cached", fourth)
                self.assertGreater(scan.call_count, second_scan_count)

    def test_chatlog_is_runtime_data_and_is_preserved_without_package_hashing(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            old = target / ".agents" / "sdd-template-1.9.5"
            new = target / ".agents" / "sdd-template-1.9.6"
            old.mkdir(parents=True)
            new.mkdir(parents=True)
            readme = old / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(old, [readme])
            source_log = old / ".chatlog" / "session.md"
            source_log.parent.mkdir()
            source_log.write_text("session data\n", encoding="utf-8")

            inventory = install_framework.inventory_release(old, expected_version="1.9.5")
            self.assertFalse(inventory["errors"])
            self.assertFalse(inventory["nonstandard_paths"])
            self.assertTrue(inventory["safe_to_delete"])
            migration = install_framework.preserve_runtime_data(old, new)
            self.assertEqual(migration["status"], "preserved")
            self.assertEqual((new / ".chatlog" / "session.md").read_text(encoding="utf-8"), "session data\n")
            source_log.write_text("newer session data\n", encoding="utf-8")
            with self.assertRaises(build_release.BuildError):
                install_framework.preserve_runtime_data(old, new)
            self.assertEqual((new / ".chatlog" / "session.md").read_text(encoding="utf-8"), "session data\n")

    def test_interrupted_alias_switch_recovers_from_structure_pointer(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            old = target / ".agents" / "sdd-template-1.9.6"
            new = target / ".agents" / "sdd-template-1.9.7"
            old.mkdir(parents=True)
            new.mkdir()
            write_consumer_structure(target, "1.9.6")
            alias = target / ".agents" / "sdd-template-current"
            install_framework.fs_boundary.create_directory_alias(alias, old)
            self.assertEqual(install_framework.installed_release(target), ("1.9.6", old))
            install_framework._begin_alias_switch(target, "1.9.6", "1.9.7")
            self.assertFalse(os.path.lexists(alias))
            self.assertEqual(install_framework.installed_release(target), ("1.9.6", old))
            write_consumer_structure(target, "1.9.7")
            self.assertEqual(install_framework.installed_release(target), ("1.9.7", new))
            install_framework._finish_alias_switch(target, "1.9.7")
            self.assertFalse(os.path.lexists(alias))

    def test_rollback_switches_alias_to_older_release(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            old = target / ".agents" / "sdd-template-1.9.5"
            current = target / ".agents" / "sdd-template-1.9.6"
            old.mkdir(parents=True)
            current.mkdir()
            write_consumer_structure(target, "1.9.6")
            alias = target / ".agents" / "sdd-template-current"
            install_framework.fs_boundary.create_directory_alias(alias, current)

            install_framework._begin_alias_switch(target, "1.9.6", "1.9.5")
            self.assertFalse(os.path.lexists(alias))
            self.assertEqual(install_framework.installed_release(target), ("1.9.6", current))
            write_consumer_structure(target, "1.9.5")
            install_framework._finish_alias_switch(target, "1.9.5")
            self.assertEqual(install_framework.installed_release(target), ("1.9.5", old))
            self.assertFalse(os.path.lexists(alias))

    def test_older_release_migrates_markdown_without_alias(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            package = target / ".agents" / "sdd-template-1.9.5"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            write_consumer_structure(target, "1.9.5")
            document = target / "AGENTS.md"
            document.write_text("[Framework](.agents/sdd-template-current/README.md)\n", encoding="utf-8")
            review = install_framework.post_install_validate(target, "1.9.5", package)
            self.assertEqual(review["status"], "blocked")
            migration = install_framework.plan_text_reference_migration(target, "1.9.5", review)
            self.assertEqual(migration["status"], "planned")
            install_framework.apply_reference_migration(target, "1.9.5", migration)
            self.assertIn(".agents/sdd-template-1.9.5/README.md", document.read_text(encoding="utf-8"))
            self.assertFalse(os.path.lexists(target / ".agents" / "sdd-template-current"))
            self.assertEqual(install_framework.post_install_validate(target, "1.9.5", package)["status"], "pass")

    def test_missing_stable_target_and_invalid_utf8_block_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            package = target / ".agents" / "sdd-template-1.9.6"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            write_consumer_structure(target, "1.9.6")
            install_framework._finish_alias_switch(target, "1.9.6")
            document = target / "AGENTS.md"
            document.write_text("[Missing](.agents/sdd-template-current/missing.md)\n", encoding="utf-8")
            review = install_framework.post_install_validate(target, "1.9.6", package)
            self.assertEqual(review["status"], "blocked")
            summary = review.get("summary")
            assert isinstance(summary, dict)
            self.assertEqual(summary.get("missing"), 1)
            self.assertEqual(install_framework.plan_text_reference_migration(
                target, "1.9.6", review
            )["status"], "blocked")
            document.write_bytes(b"invalid \xff utf8\n")
            review = install_framework.post_install_validate(target, "1.9.6", package)
            self.assertEqual(review["status"], "blocked")
            errors = review.get("errors")
            assert isinstance(errors, list)
            self.assertTrue(
                any(isinstance(error, str) and "Невозможно проверить ссылки" in error for error in errors)
            )

    def test_historical_local_markdown_blocks_old_release_removal(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            current = target / ".agents" / "sdd-template-1.9.6"
            old = target / ".agents" / "sdd-template-1.9.5"
            current.mkdir(parents=True)
            old.mkdir()
            current_readme = current / "README.md"
            old_readme = old / "README.md"
            current_readme.write_text("current\n", encoding="utf-8")
            old_readme.write_text("old\n", encoding="utf-8")
            write_consumer_manifest(current, [current_readme])
            write_consumer_manifest(old, [old_readme])
            write_consumer_structure(target, "1.9.6")
            install_framework._finish_alias_switch(target, "1.9.6")
            archived = target / ".tasks" / "done" / "TD.md"
            archived.parent.mkdir(parents=True)
            archived.write_text("[Old](../../.agents/sdd-template-1.9.5/README.md)\n", encoding="utf-8")
            review = install_framework.post_install_validate(target, "1.9.6", current)
            self.assertEqual(review["status"], "pass")
            links = install_framework.historical_links_to_release(review, "1.9.5")
            self.assertEqual(len(links), 1)
            self.assertEqual(install_framework.historical_link_block(links, "1.9.5")["status"], "installed_pending_review")
            old_readme.unlink()
            review = install_framework.post_install_validate(target, "1.9.6", current)
            self.assertEqual(review["status"], "blocked")
            summary = review.get("summary")
            assert isinstance(summary, dict)
            self.assertEqual(summary.get("missing"), 1)

    def test_post_install_gate_rejects_alias_to_other_release(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.6")
            package = target / ".agents" / "sdd-template-1.9.6"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            other = target / ".agents" / "sdd-template-1.9.5"
            other.mkdir()
            install_framework.fs_boundary.create_directory_alias(
                target / ".agents" / "sdd-template-current", other
            )
            result = install_framework.post_install_validate(target, "1.9.6", package)
            self.assertEqual(result["status"], "blocked")
            errors = result.get("errors")
            assert isinstance(errors, list)
            self.assertTrue(
                any(isinstance(error, str) and "Постоянный адрес" in error for error in errors)
            )

    def test_external_alias_is_not_accepted_as_active_release(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            target = root / "consumer"
            package = target / ".agents" / "sdd-template-1.9.6"
            package.mkdir(parents=True)
            write_consumer_structure(target, "1.9.6")
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "marker.txt"
            marker.write_bytes(b"preserve")
            alias = target / ".agents" / "sdd-template-current"
            if os.name == "nt":
                created = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(alias), str(outside)],
                    capture_output=True, text=True, check=False,
                )
                if created.returncode != 0:
                    self.skipTest(f"Windows junction unavailable: {created.stderr.strip()}")
            else:
                alias.symlink_to(outside, target_is_directory=True)
            with self.assertRaises((OSError, build_release.BuildError)):
                install_framework.installed_release(target)
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_post_install_gate_requires_matching_release_pointer(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.1")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(review["status"], "blocked")
            self.assertTrue(any("framework.release_dir" in error for error in review["errors"]))

    def test_post_install_gate_blocks_reparse_scan_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            with patch.object(
                install_framework.build_release,
                "is_link_or_reparse_point",
                side_effect=lambda path: path == target / "docs",
            ):
                review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(review["status"], "blocked")
            self.assertTrue(any("docs" in error for error in review["errors"]))

    def test_relative_markdown_links_check_depth_and_encoded_spaces(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            template = package / ".requirements" / "структура Данных" / "шаблоны карточек.md"
            template.parent.mkdir(parents=True)
            template.write_text("framework\n", encoding="utf-8")
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme, template])
            deep = target / "docs" / "requirements" / "сценарии" / "timer"
            shallow = target / "docs" / "requirements" / "тестирование"
            deep.mkdir(parents=True)
            shallow.mkdir(parents=True)
            (deep / "карта процесса.md").write_text(
                "[шаблон](../../../../.agents/sdd-template-1.9.2/.requirements/структура%20Данных/шаблоны%20карточек.md)\n",
                encoding="utf-8",
            )
            (shallow / "испытание системы.md").write_text(
                "[шаблон](../../../.agents/sdd-template-1.9.1/.requirements/структура%20Данных/шаблоны%20карточек.md)\n",
                encoding="utf-8",
            )
            review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(review["summary"]["valid"], 2)
            self.assertEqual(review["summary"]["stale"], 1)
            self.assertEqual(review["status"], "blocked")
            self.assertEqual(review["unresolved"][0]["source"], "markdown")

    def test_project_tools_path_is_not_mistaken_for_framework(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            own_tools = target / ".tools"
            own_tools.mkdir()
            (own_tools / "runner.py").write_text("pass\n", encoding="utf-8")
            (target / "AGENTS.md").write_text("Use .tools/runner.py\n", encoding="utf-8")
            review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(review["status"], "pass")
            self.assertEqual(review["summary"]["project"], 1)

    def test_archived_version_reference_does_not_hide_active_stale_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            archived = target / ".tasks" / "done"
            archived.mkdir(parents=True)
            (archived / "TD-old.md").write_text(
                "Used .agents/sdd-template-1.9.1/README.md\n", encoding="utf-8"
            )
            (target / ".tasks" / "TD-current.md").write_text(
                "Use .agents/sdd-template-1.9.1/README.md\n", encoding="utf-8"
            )
            result = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(result["summary"]["historical"], 1)
            self.assertEqual(result["summary"]["stale"], 1)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["unresolved"][0]["file"], ".tasks/TD-current.md")

    def test_post_install_gate_blocks_unreadable_utf8_document(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            (target / "AGENTS.md").write_bytes(b"\xff")

            result = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(any("AGENTS.md" in error for error in result["errors"]))

    def test_post_install_gate_blocks_modified_or_extra_package_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])

            self.assertEqual(install_framework.post_install_validate(target, "1.9.2", package)["status"], "pass")
            readme.write_text("changed\n", encoding="utf-8")
            modified = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(modified["status"], "blocked")
            self.assertTrue(any("README.md" in error for error in modified["errors"]))

            readme.write_text("framework\n", encoding="utf-8")
            (package / "extra.txt").write_text("unknown\n", encoding="utf-8")
            extra = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(extra["status"], "blocked")
            self.assertTrue(any("extra.txt" in error for error in extra["errors"]))

    def test_post_install_gate_blocks_wrong_release_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            manifest_path = package / "release-manifest.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))

            for field, wrong_value in (
                ("package_id", "other"),
                ("version", "1.9.1"),
                ("release_dir", ".agents/sdd-template-1.9.1"),
            ):
                changed = {**original, field: wrong_value}
                manifest_path.write_text(json.dumps(changed), encoding="utf-8")
                review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
                self.assertEqual(review["status"], "blocked", field)
                self.assertTrue(any("Идентичность" in error for error in review["errors"]), field)

    def test_text_migration_plan_is_precise_and_rejects_changed_document(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            manifest = package / ".manifest" / "taskmanifest.md"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [manifest])
            document = target / "docs" / "requirements" / "обоснование выбора.md"
            document.parent.mkdir(parents=True)
            original = (
                "Use `.agents/sdd-template-1.9.1/.manifest/taskmanifest.md`.\n"
                "[task](../../.agents/sdd-template-1.9.1/.manifest/taskmanifest.md)\n"
            )
            document.write_text(original, encoding="utf-8")

            review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            plan = cast(dict[str, Any], install_framework.plan_text_reference_migration(target, "1.9.2", review))
            self.assertEqual(plan["status"], "blocked")
            self.assertEqual(len(plan["changes"]), 1)
            change = plan["changes"][0]
            self.assertEqual(change["old"], ".agents/sdd-template-1.9.1/.manifest/taskmanifest.md")
            self.assertEqual(change["new"], "FRAMEWORK_ROOT/.manifest/taskmanifest.md")
            self.assertEqual(original[change["start"]:change["end"]], change["old"])
            self.assertEqual(len(plan["blocked_references"]), 1)
            self.assertEqual(plan["blocked_references"][0]["source"], "markdown")
            self.assertEqual(document.read_text(encoding="utf-8"), original)
            compact = cast(dict[str, Any], install_framework.compact_report(plan))
            self.assertEqual(compact["changes_count"], 1)
            self.assertNotIn("changes", compact)

            document.write_text(original + "changed\n", encoding="utf-8")
            changed = cast(dict[str, Any], install_framework.plan_text_reference_migration(target, "1.9.2", review))
            self.assertEqual(changed["status"], "blocked")
            self.assertEqual(changed["changes"], [])
            self.assertTrue(changed["errors"])

    def test_text_uses_framework_root_and_markdown_migrates_versions(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.6")
            package = target / ".agents" / "sdd-template-1.9.6"
            template = package / ".requirements" / "структура Данных" / "шаблоны карточек.md"
            template.parent.mkdir(parents=True)
            template.write_text("framework\n", encoding="utf-8")
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [template, readme])
            alias = target / ".agents" / "sdd-template-current"
            install_framework.fs_boundary.create_directory_alias(alias, package)
            deep = target / "docs" / "requirements" / "сценарии" / "timer"
            shallow = target / "docs" / "requirements" / "тестирование"
            deep.mkdir(parents=True)
            shallow.mkdir(parents=True)
            first = deep / "карта процесса.md"
            second = shallow / "испытание системы.md"
            old_package = target / ".agents" / "sdd-template-1.9.5"
            old_template = old_package / ".requirements" / "структура Данных" / "шаблоны карточек.md"
            old_template.parent.mkdir(parents=True)
            old_template.write_text("old framework\n", encoding="utf-8")
            old_readme = old_package / "README.md"
            old_readme.write_text("old framework\n", encoding="utf-8")
            write_consumer_manifest(old_package, [old_template, old_readme])
            first.write_text(
                "[шаблон](../../../../.agents/sdd-template-1.9.6/.requirements/структура%20Данных/шаблоны%20карточек.md)\n",
                encoding="utf-8",
            )
            second.write_text(
                "[шаблон](../../../.agents/sdd-template-1.9.5/.requirements/структура%20Данных/шаблоны%20карточек.md)\n",
                encoding="utf-8",
            )
            text_document = target / "AGENTS.md"
            text_document.write_text(
                "Use .agents/sdd-template-1.9.6/README.md\n",
                encoding="utf-8",
            )
            review = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.6", package))
            self.assertEqual(review["status"], "blocked")
            plan = cast(dict[str, Any], install_framework.plan_text_reference_migration(target, "1.9.6", review))
            self.assertEqual(plan["status"], "planned")
            self.assertEqual(len(plan["changes"]), 1)
            result = cast(dict[str, Any], install_framework.apply_reference_migration(target, "1.9.6", plan))
            self.assertEqual(result["status"], "applied")
            self.assertIn("sdd-template-1.9.6", first.read_text(encoding="utf-8"))
            self.assertNotIn("sdd-template-current", first.read_text(encoding="utf-8"))
            self.assertIn("sdd-template-1.9.6", second.read_text(encoding="utf-8"))
            self.assertIn("%20", first.read_text(encoding="utf-8"))
            self.assertIn("sdd-template-1.9.6", text_document.read_text(encoding="utf-8"))
            self.assertEqual(install_framework.post_install_validate(target, "1.9.6", package)["status"], "pass")

            next_package = target / ".agents" / "sdd-template-1.9.7"
            next_template = next_package / ".requirements" / "структура Данных" / "шаблоны карточек.md"
            next_template.parent.mkdir(parents=True)
            next_template.write_text("next\n", encoding="utf-8")
            next_readme = next_package / "README.md"
            next_readme.write_text("next\n", encoding="utf-8")
            write_consumer_manifest(next_package, [next_template, next_readme])
            install_framework.fs_boundary.remove_directory_alias(alias, package)
            write_consumer_structure(target, "1.9.7")
            next_review = install_framework.post_install_validate(target, "1.9.7", next_package)
            self.assertEqual(next_review["status"], "blocked")
            next_plan = install_framework.plan_text_reference_migration(target, "1.9.7", next_review)
            self.assertEqual(next_plan["status"], "planned")
            changes = next_plan.get("changes")
            if not isinstance(changes, list):
                self.fail("Reference migration plan must contain a changes list")
            self.assertEqual(len(changes), 3)
            install_framework.apply_reference_migration(target, "1.9.7", next_plan)
            self.assertEqual(install_framework.post_install_validate(target, "1.9.7", next_package)["status"], "pass")

    def test_reference_apply_rejects_document_changed_after_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.6")
            package = target / ".agents" / "sdd-template-1.9.6"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            install_framework.fs_boundary.create_directory_alias(
                target / ".agents" / "sdd-template-current", package
            )
            document = target / "AGENTS.md"
            original = "Use .agents/sdd-template-1.9.5/README.md\n"
            document.write_text(original, encoding="utf-8")
            review = install_framework.post_install_validate(target, "1.9.6", package)
            plan = install_framework.plan_text_reference_migration(target, "1.9.6", review)
            self.assertEqual(plan["status"], "planned")
            document.write_text(original + "user edit\n", encoding="utf-8")
            with self.assertRaises(build_release.BuildError):
                install_framework.apply_reference_migration(target, "1.9.6", plan)
            self.assertIn("user edit", document.read_text(encoding="utf-8"))
            document.write_text(original, encoding="utf-8")
            readme.write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(build_release.BuildError):
                install_framework.apply_reference_migration(target, "1.9.6", plan)
            self.assertEqual(document.read_text(encoding="utf-8"), original)

    def test_compact_report_keeps_conflicts_and_fingerprints(self) -> None:
        report: dict[str, Any] = {
            "status": "installed_pending_review",
            "old_release": {"inventory": {
                "fingerprint": "old-hash", "entries": [{"path": "README.md"}],
                "nonstandard_paths": ["custom.txt"], "skipped_service_paths": [],
                "summary": {"entries": 1, "classifications": {"framework": 1, "user_data": 1}},
                "errors": [],
            }},
            "post_install_review": {
                "status": "blocked", "checked_files": ["AGENTS.md"],
                "references": [{"classification": "valid"}],
                "unresolved": [{"classification": "stale", "file": "AGENTS.md"}],
                "checked_files_fingerprint": "docs-hash", "errors": [],
            },
            "next_action": {"type": "user_confirmation", "fingerprint": "old-hash"},
        }
        compact = cast(dict[str, Any], install_framework.compact_report(report))
        self.assertEqual(compact["old_release"]["inventory"]["fingerprint"], "old-hash")
        self.assertEqual(compact["old_release"]["inventory"]["nonstandard_paths"], ["custom.txt"])
        self.assertEqual(
            compact["old_release"]["inventory"]["summary"],
            report["old_release"]["inventory"]["summary"],
        )
        self.assertNotIn("entries", compact["old_release"]["inventory"])
        self.assertEqual(compact["post_install_review"]["checked_files_count"], 1)
        self.assertEqual(compact["post_install_review"]["unresolved"][0]["file"], "AGENTS.md")
        self.assertNotIn("references", compact["post_install_review"])
        self.assertEqual(compact["post_install_review"]["checked_files_fingerprint"], "docs-hash")
        self.assertEqual(compact["post_install_review"]["errors"], [])
        self.assertEqual(compact["next_action"], report["next_action"])
        self.assertEqual(report["old_release"]["inventory"]["entries"], [{"path": "README.md"}])

    def test_post_install_gate_classifies_stale_and_external_references(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            (target / "AGENTS.md").write_text(
                "See .agents/sdd-template-1.9.1/.manifest/taskmanifest.md\n"
                "External: https://example.test/.manifest/taskmanifest.md\n",
                encoding="utf-8",
            )

            result = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["summary"]["stale"], 1)
            self.assertEqual(result["summary"]["external"], 1)
            self.assertEqual(len(result["unresolved"]), 1)

    def test_post_install_gate_passes_for_current_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            target = Path(temporary)
            write_consumer_structure(target, "1.9.2")
            package = target / ".agents" / "sdd-template-1.9.2"
            package.mkdir(parents=True)
            readme = package / "README.md"
            readme.write_text("framework\n", encoding="utf-8")
            write_consumer_manifest(package, [readme])
            (target / "AGENTS.md").write_text(
                ".agents/sdd-template-1.9.2/README.md\n",
                encoding="utf-8",
            )

            result = cast(dict[str, Any], install_framework.post_install_validate(target, "1.9.2", package))
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["unresolved"], [])


class ShellLibraryExportTests(unittest.TestCase):
    def test_release_stage_includes_generator_and_shell_assets_but_not_tests(self) -> None:
        root = build_release.repository_root()
        version = build_release.read_version(root)
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            stage = Path(temporary) / "stage"
            build_release.build_stage(root, version, stage)

            library = stage / ".tools" / "ui-screen-scaffold" / "shells"
            manifest = json.loads((library / "shell-library.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["shells"]), 41)
            self.assertTrue((library / "shell.css").is_file())
            self.assertTrue((stage / ".tools" / "ui-screen-scaffold" / "ui_screen_scaffold.py").is_file())
            self.assertTrue((stage / ".tools" / "ui-screen-scaffold" / "ui-screen-scaffold.bat").is_file())
            self.assertFalse((stage / ".tools" / "ui-screen-scaffold" / "tests").exists())
            for shell in manifest["shells"]:
                shell_page = library / shell["path"]
                self.assertTrue(shell_page.is_file(), shell["path"])
                self.assertTrue((shell_page.parent / shell["stylesheet"]).is_file(), shell["stylesheet"])

            registry = json.loads((stage / ".tools" / "registry.json").read_text(encoding="utf-8"))
            self.assertIn("ui-screen-scaffold", {entry["name"] for entry in registry})
            release_manifest = json.loads((stage / "release-manifest.json").read_text(encoding="utf-8"))
            package_paths = {entry["path"] for entry in release_manifest["files"]}
            self.assertIn(".tools/ui-screen-scaffold/shells/shell-library.json", package_paths)
            self.assertIn(".tools/ui-screen-scaffold/ui_screen_scaffold.py", package_paths)
            self.assertNotIn(".tools/ui-screen-scaffold/tests/test_viewport_catalog.py", package_paths)


if __name__ == "__main__":
    unittest.main()
