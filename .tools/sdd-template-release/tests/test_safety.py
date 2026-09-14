import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
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


class SafetyInventoryTests(unittest.TestCase):
    def test_release_inventory_detects_figma_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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

            self.assertTrue(inventory["safe_to_delete"])
            self.assertEqual(inventory["top_level_nonstandard"], [".figma"])
            self.assertIn(".figma/Samsung A51-A71/screen.html", inventory["nonstandard_paths"])
            self.assertEqual(inventory["summary"]["user_data_entries"], 3)

    def test_cleanup_requires_fingerprint_and_detects_untracked_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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
        with tempfile.TemporaryDirectory() as temporary:
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

    def test_cleanup_inventory_separates_generated_staging_from_extra_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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

    def test_build_can_stage_new_release_with_old_release_present_only_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            source = target / "tmp" / "sdd-template-source-1.9.1-12345678"
            source.mkdir(parents=True)
            old_release = target / ".agents" / "sdd-template-1.9.0"
            old_release.mkdir(parents=True)
            readme = old_release / "README.md"
            readme.write_text("old", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
