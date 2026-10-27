import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TOOL_DIR = Path(__file__).resolve().parents[1]
TEST_TMP = TOOL_DIR.parents[1] / "tmp"
sys.path.insert(0, str(TOOL_DIR))

import ui_reference  # noqa: E402


class UiReferenceTests(unittest.TestCase):
    def test_migration_rejects_parent_swap_before_write(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "asset.txt").write_bytes(b"source")
            target = root / "target"
            target.mkdir()
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "asset.txt"
            marker.write_bytes(b"preserve")
            destination = target / "asset.txt"
            original_write = ui_reference.fs_boundary.write_bytes
            swapped = False

            def write_after_swap(path: Path, content: bytes, *, create_only: bool = False) -> None:
                nonlocal swapped
                if path == destination and not swapped:
                    swapped = True
                    target.rename(root / "moved")
                    try:
                        target.symlink_to(outside, target_is_directory=True)
                    except (OSError, NotImplementedError) as error:
                        self.skipTest(f"Directory symlinks unavailable: {error}")
                original_write(path, content, create_only=create_only)

            with patch.object(ui_reference.fs_boundary, "write_bytes", side_effect=write_after_swap):
                result = ui_reference.migrate(source, target, True)
            self.assertTrue(swapped)
            self.assertEqual(result["status"], "conflicts")
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_tool_version_matches_registry(self) -> None:
        readme = (TOOL_DIR / "README.md").read_text(encoding="utf-8")
        registry = json.loads((TOOL_DIR.parent / "registry.json").read_text(encoding="utf-8"))
        version_match = re.search(r"Версия инструмента: `([0-9]+\.[0-9]+\.[0-9]+)`", readme)
        tool_entry = next(entry for entry in registry if entry.get("name") == "ui-reference")

        if version_match is None:
            self.fail("Версия инструмента не найдена в README")
        self.assertEqual(tool_entry["version"], version_match.group(1))

    def _write_valid_package(self, root: Path) -> None:
        (root / "screens").mkdir(parents=True)
        (root / "references").mkdir()
        (root / "README.md").write_text("UI package\n", encoding="utf-8")
        (root / "screens" / "dashboard.md").write_text("# Dashboard\n", encoding="utf-8")
        (root / "пул-экранов.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "screens": [
                        {
                            "screen_id": "dashboard",
                            "title": "Dashboard",
                            "screen_type": "dashboard",
                            "purpose": "View metrics",
                            "user_roles": ["operator"],
                            "user_task": "Review metrics",
                            "pattern_candidates": [
                                {"pattern_id": "pattern.dashboard", "status": "selected"}
                            ],
                            "template_candidates": [
                                {"template_id": "template.dashboard", "status": "selected"}
                            ],
                            "states": ["initial"],
                            "transitions": [],
                            "viewport_candidates": [{"width": 1280, "height": 720}],
                            "source_refs": ["REQ-1"],
                            "status": "confirmed",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (root / "манифест-спецификации-интерфейса.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "template_set_version": "0.2.0",
                    "source_url": ui_reference.SOURCE_URL,
                    "revision": "abc123",
                    "contract_version": "1",
                    "status": "confirmed",
                    "screen_pool": "пул-экранов.json",
                    "screens": [
                        {
                            "screen_id": "dashboard",
                            "specification": "screens/dashboard.md",
                            "status": "confirmed",
                            "pattern_refs": ["pattern.dashboard"],
                            "template_refs": ["template.dashboard"],
                            "reference_artifacts": [],
                        }
                    ],
                    "reference_sets": [],
                    "traceability": [
                        {
                            "screen_id": "dashboard",
                            "requirement_refs": ["REQ-1"],
                            "scenario_refs": ["SCN-1"],
                            "acceptance_criteria": ["AC-1"],
                        }
                    ],
                    "gaps": [],
                }
            ),
            encoding="utf-8",
        )

    def _write_v2_package(
        self,
        root: Path,
        workflow_mode: str = "track-integrated",
        template_set_version: str = "0.3.0",
        revision: str = "410b2ff4280cee7ef72c0e1834e2841ba3daf52d",
    ) -> None:
        (root / "screens").mkdir(parents=True)
        reference_root = root / "references" / "reference-set-a"
        viewport_root = reference_root / "desktop"
        viewport_root.mkdir(parents=True)
        (root / "README.md").write_text("UI package\n", encoding="utf-8")
        (root / "screens" / "screen-a.md").write_text("# Screen A\n", encoding="utf-8")
        (root / "screens" / "screen-b.md").write_text("# Screen B\n", encoding="utf-8")
        for filename, content in (
            ("index.html", "<a href='screen-a.html'>A</a>\n"),
            ("reference-manifest.json", "{}\n"),
            ("README.md", "Reference set\n"),
            ("screen-a.html", "<main>A</main>\n"),
            ("screen-b.html", "<main>B</main>\n"),
        ):
            (viewport_root / filename).write_text(content, encoding="utf-8")

        viewport = {
            "viewport_id": "desktop",
            "width": 1280,
            "height": 720,
            "unit": "css-px",
            "orientation": "landscape",
        }
        shell_candidate = {
            "status": "selected",
            "catalog_url": "https://example.invalid/shell-catalog.git",
            "catalog_revision": "1" * 40,
            "shell_id": "shell.desktop.landscape",
            "shell_version": "1.0.0",
            "shell_viewport": {
                "width": 1280,
                "height": 720,
                "unit": "css-px",
                "orientation": "landscape",
            },
            "rationale": "Synthetic selected shell candidate.",
        }
        pool_screens = []
        manifest_screens = []
        traceability = []
        artifacts = []
        for suffix in ("a", "b"):
            screen_id = f"screen-{suffix}"
            artifact_id = f"artifact-{suffix}"
            pool_screens.append(
                {
                    "screen_id": screen_id,
                    "title": f"Screen {suffix.upper()}",
                    "screen_type": "dashboard",
                    "purpose": "Review project information",
                    "user_roles": ["operator"],
                    "user_task": "Review information",
                    "pattern_candidates": [
                        {
                            "pattern_id": "ui.pattern.shared",
                            "status": "selected",
                            "rationale": "Shared pattern is suitable for both screens",
                            "source_refs": ["SRC-1"],
                        }
                    ],
                    "template_candidates": [
                        {
                            "template_id": "ui.template.shared",
                            "status": "selected",
                            "rationale": "Shared template is suitable for both screens",
                            "source_refs": ["SRC-1"],
                        }
                    ],
                    "states": ["initial"],
                    "transitions": [],
                    "viewport_candidates": [
                        {
                            **viewport,
                            "status": "confirmed",
                            "rationale": "Synthetic test viewport",
                            "source_refs": ["SRC-1"],
                            **(
                                {
                                    "responsive_profile": "wide",
                                    "breakpoint_conditions": "Synthetic test breakpoint condition.",
                                    "purpose": "reference",
                                    "source": "test-fixture:viewport",
                                    "screen_shell_candidates": [shell_candidate.copy()],
                                }
                                if ui_reference._requires_shell_integration(template_set_version)
                                else {}
                            ),
                        }
                    ],
                    "source_refs": ["SRC-1"],
                    "status": "confirmed",
                }
            )
            manifest_screens.append(
                {
                    "screen_id": screen_id,
                    "specification": f"screens/{screen_id}.md",
                    "status": "confirmed",
                    "pattern_refs": ["ui.pattern.shared"],
                    "template_refs": ["ui.template.shared"],
                    "reference_artifacts": [artifact_id],
                }
            )
            traceability.append(
                {
                    "screen_id": screen_id,
                    "requirement_refs": [f"REQ-{suffix.upper()}"],
                    "scenario_refs": [f"SCN-{suffix.upper()}"],
                    "acceptance_criteria": [f"AC-{suffix.upper()}"],
                }
            )
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "screen_id": screen_id,
                    "role": "operator",
                    "state": "initial",
                    "viewport": viewport.copy(),
                    "path": f"desktop/screen-{suffix}.html",
                    "pattern_refs": ["ui.pattern.shared"],
                    "template_refs": ["ui.template.shared"],
                }
            )

        (root / "пул-экранов.json").write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "contract_version": "2",
                    "workflow_mode": workflow_mode,
                    "template_set_version": template_set_version,
                    "status": "confirmed",
                    "source_refs": ["SRC-1"],
                    "screens": pool_screens,
                }
            ),
            encoding="utf-8",
        )
        (root / "манифест-спецификации-интерфейса.json").write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "contract_version": "2",
                    "workflow_mode": workflow_mode,
                    "template_set_version": template_set_version,
                    "source_url": ui_reference.SOURCE_URL,
                    "revision": revision,
                    "status": "confirmed",
                    "screen_pool": "пул-экранов.json",
                    "screens": manifest_screens,
                    "reference_sets": [
                        {"reference_set_id": "reference-set-a", "path": "references/reference-set-a"}
                    ],
                    "traceability": traceability,
                    "gaps": [],
                }
            ),
            encoding="utf-8",
        )
        (reference_root / "screen-manifest.json").write_text(
            json.dumps(
            {
                "schema_version": "2.0",
                "contract_version": "2",
                "reference_set_id": "reference-set-a",
                "template_set_version": template_set_version,
                "source_url": ui_reference.SOURCE_URL,
                "revision": revision,
                "artifacts": artifacts,
                }
            ),
            encoding="utf-8",
        )

    def _add_shell_bindings(self, root: Path, status: str = "selected") -> None:
        reference_manifest_path = root / "references" / "reference-set-a" / "screen-manifest.json"
        reference_manifest = json.loads(reference_manifest_path.read_text(encoding="utf-8"))
        for artifact in reference_manifest["artifacts"]:
            binding = {
                "status": status,
                "catalog_url": "https://example.invalid/shell-catalog.git",
                "catalog_revision": "1" * 40,
                "shell_id": "shell.desktop.landscape",
                "shell_version": "1.0.0",
                "viewport_id": "desktop",
                "shell_viewport": {
                    "width": 1280,
                    "height": 720,
                    "unit": "css-px",
                    "orientation": "landscape",
                },
            }
            if status == "proposed":
                binding["rationale"] = "Synthetic shell candidate for validator tests."
            elif status == "gap":
                binding = {
                    "status": "gap",
                    "viewport_id": "desktop",
                    "reason": "Подходящая оболочка пока не определена.",
                    "decision_needed": "Подтвердить каталог оболочек или заказать его создание.",
                }
            elif status == "not_applicable":
                binding = {
                    "status": "not_applicable",
                    "rationale": "Представление не является визуальным экраном.",
                }
            artifact["shell_binding"] = binding
        reference_manifest_path.write_text(
            json.dumps(reference_manifest), encoding="utf-8"
        )
        pool_path = root / "пул-экранов.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        for screen in pool["screens"]:
            viewport_candidate = screen["viewport_candidates"][0]
            if status in {"selected", "proposed"}:
                candidate = {
                    "status": status,
                    "catalog_url": "https://example.invalid/shell-catalog.git",
                    "catalog_revision": "1" * 40,
                    "shell_id": "shell.desktop.landscape",
                    "shell_version": "1.0.0",
                    "shell_viewport": {
                        "width": 1280,
                        "height": 720,
                        "unit": "css-px",
                        "orientation": "landscape",
                    },
                    "rationale": "Synthetic shell candidate for validator tests.",
                }
            elif status == "gap":
                candidate = {
                    "status": "gap",
                    "reason": "Подходящая оболочка пока не определена.",
                    "decision_needed": "Подтвердить каталог оболочек или заказать его создание.",
                }
            else:
                candidate = {
                    "status": "not_applicable",
                    "rationale": "Представление не является визуальным экраном.",
                }
            viewport_candidate["screen_shell_candidates"] = [candidate]
        pool_path.write_text(json.dumps(pool), encoding="utf-8")

    def test_validate_reference_set(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "reference-set"
            viewport = root / "412x914px"
            viewport.mkdir(parents=True)
            (viewport / "index.html").write_text("<a href='screen.html'>screen</a>\n", encoding="utf-8")
            (viewport / "README.md").write_text("Reference\n", encoding="utf-8")
            (viewport / "reference-manifest.json").write_text(
                json.dumps({"screens": [{"file": "screen.html"}]}), encoding="utf-8"
            )
            (viewport / "screen.html").write_text("<main>screen</main>\n", encoding="utf-8")
            (root / "screen-manifest.json").write_text(
                json.dumps(
                    {
                        "screens": [
                            {
                                "file": "412x914px/screen.html",
                                "viewport": {"width": 412, "height": 914},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            errors: list[str] = []
            ui_reference.validate_reference_set(root, errors)
            self.assertEqual(errors, [])

    def test_v2_accepts_nested_screen_viewport_layout(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            reference_root = root / "references" / "reference-set-a"
            reference_manifest_path = reference_root / "screen-manifest.json"
            reference_manifest = json.loads(reference_manifest_path.read_text(encoding="utf-8"))
            for artifact in reference_manifest["artifacts"]:
                artifact["path"] = f"screens/{artifact['screen_id']}/desktop/index.html"
                directory = reference_root / "screens" / artifact["screen_id"] / "desktop"
                directory.mkdir(parents=True)
                (directory / "index.html").write_text("<main></main>\n", encoding="utf-8")
                (directory / "reference-manifest.json").write_text("{}\n", encoding="utf-8")
                (directory / "README.md").write_text("Reference\n", encoding="utf-8")
            reference_manifest_path.write_text(json.dumps(reference_manifest), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "pass", errors)

    def test_local_framework_shell_checks_id_version_geometry_and_commit(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            framework = Path(temporary)
            library_path = framework / ".tools" / "ui-screen-scaffold" / "shells" / "shell-library.json"
            library_path.parent.mkdir(parents=True)
            shell = {
                "shell_id": "shell.test.mobile",
                "shell_version": "1.2.3",
                "viewport_id": "vp-test-412x915",
                "width": 412,
                "height": 915,
                "unit": "css-px",
                "orientation": "portrait",
            }
            library_path.write_text(json.dumps({"shells": [shell]}), encoding="utf-8")
            commit = "a" * 40
            (framework / "release-manifest.json").write_text(
                json.dumps({"package_id": "sdd-template", "source_commit": commit}), encoding="utf-8"
            )
            value = {
                "catalog_url": ui_reference.FRAMEWORK_URL,
                "catalog_revision": commit,
                "shell_id": "shell.test.mobile",
                "shell_version": "1.2.3",
                "viewport_id": "vp-test-412x915",
                "shell_viewport": {
                    "width": 412,
                    "height": 915,
                    "unit": "css-px",
                    "orientation": "portrait",
                },
            }
            errors: list[str] = []
            ui_reference._validate_local_shell(value, "shell_binding", errors, framework)
            self.assertEqual(errors, [])

            mutations = (
                ("shell_version", "9.9.9", "shell_version"),
                ("catalog_revision", "b" * 40, "catalog_revision"),
                ("shell_id", "shell.unknown", "shell_id"),
            )
            for key, replacement, expected in mutations:
                with self.subTest(field=key):
                    invalid = {**value, key: replacement}
                    errors = []
                    ui_reference._validate_local_shell(invalid, "shell_binding", errors, framework)
                    self.assertTrue(any(expected in error for error in errors), errors)

            invalid_geometry = {**value, "shell_viewport": {**value["shell_viewport"], "width": 390}}
            errors = []
            ui_reference._validate_local_shell(invalid_geometry, "shell_binding", errors, framework)
            self.assertTrue(any("shell_viewport.width" in error for error in errors), errors)

    def test_validate_v2_reference_set_and_contract_schemas(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            reference_root = root / "references" / "reference-set-a"
            reference_manifest = json.loads(
                (reference_root / "screen-manifest.json").read_text(encoding="utf-8")
            )
            errors: list[str] = []

            ui_reference.validate_reference_set(
                reference_root,
                errors,
                reference_manifest["contract_version"],
                reference_manifest["reference_set_id"],
            )

            self.assertEqual(errors, [])

        schema_root = TOOL_DIR.parents[1] / ".requirements" / "пользовательский-интерфейс" / "схемы"
        schema_names = (
            "манифест-спецификации-интерфейса.schema.json",
            "пул-экранов.schema.json",
            "screen-manifest.schema.json",
        )
        for schema_name in schema_names:
            schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")
            self.assertEqual(schema["properties"]["contract_version"]["const"], "2")

        template_root = schema_root.parent
        for template_name in (
            "манифест-спецификации-интерфейса.json",
            "пул-экранов.json",
            "screen-manifest.json",
        ):
            template = json.loads((template_root / template_name).read_text(encoding="utf-8"))
            self.assertEqual(template["contract_version"], "2")
        pool_template = json.loads((template_root / "пул-экранов.json").read_text(encoding="utf-8"))
        self.assertEqual(pool_template["workflow_mode"], "early-prototype")
        self.assertEqual(pool_template["screens"][0]["pattern_candidates"][0]["status"], "gap")
        self.assertEqual(pool_template["screens"][0]["template_candidates"][0]["status"], "gap")
        self.assertEqual(pool_template["screens"][0]["viewport_candidates"][0]["status"], "gap")
        self.assertEqual(
            pool_template["screens"][0]["viewport_candidates"][0]["screen_shell_candidates"][0]["status"],
            "gap",
        )

    def test_migration_does_not_overwrite_or_delete(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            (source / "same.txt").write_text("same\n", encoding="utf-8")
            (source / "conflict.txt").write_text("source\n", encoding="utf-8")
            (target / "same.txt").write_text("same\n", encoding="utf-8")
            (target / "conflict.txt").write_text("target\n", encoding="utf-8")

            report = ui_reference.migrate(source, target, write=True)

            self.assertEqual(report["status"], "conflicts")
            self.assertEqual(report["conflicts"], ["conflict.txt"])
            self.assertEqual((target / "conflict.txt").read_text(encoding="utf-8"), "target\n")
            self.assertTrue(source.exists())

    def test_migration_does_not_follow_dangling_destination_symlink(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            (source / "leak.txt").write_text("source\n", encoding="utf-8")
            outside = base / "outside.txt"
            try:
                (target / "leak.txt").symlink_to(outside)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            report = ui_reference.migrate(source, target, write=True)

            self.assertEqual(report["status"], "conflicts")
            self.assertEqual(report["conflicts"], ["leak.txt"])
            self.assertFalse(outside.exists())

    def test_migration_does_not_follow_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "target"
            (source / "nested").mkdir(parents=True)
            target.mkdir()
            (source / "nested" / "created.txt").write_text("source\n", encoding="utf-8")
            outside = base / "outside"
            try:
                (target / "nested").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            report = ui_reference.migrate(source, target, write=True)

            self.assertEqual(report["status"], "conflicts")
            self.assertEqual(report["conflicts"], ["nested/created.txt"])
            self.assertFalse(outside.exists())

    def test_validate_full_package_and_traceability(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_valid_package(root)

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "pass")
            self.assertEqual(errors, [])

    def test_v2_allows_shared_pattern_and_template_ids_across_screens(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "pass", errors)
            self.assertEqual(errors, [])

    def test_v2_rejects_duplicate_candidate_within_one_screen(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][0]["pattern_candidates"].append(
                pool["screens"][0]["pattern_candidates"][0].copy()
            )
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("повторный pattern_id внутри одного экрана" in error for error in errors))

    def test_v2_rejects_candidate_reference_from_another_screen(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][1]["pattern_candidates"][0]["pattern_id"] = "ui.pattern.only-a"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("не заявленный для экрана screen-b" in error for error in errors))

    def test_v2_track_integrated_requires_selected_candidates(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][0]["pattern_candidates"][0]["status"] = "proposed"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("должен ссылаться на выбранный candidate" in error for error in errors))

    def test_v2_checks_artifact_role_state_viewport_and_screen_mapping(self) -> None:
        mutations = (
            ("role", "admin", "роль"),
            ("state", "loading", "состояние"),
            ("screen_id", "screen-unknown", "неизвестный экран"),
        )
        for field, value, expected_error in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
                root = Path(temporary) / "ui-package"
                root.mkdir()
                self._write_v2_package(root)
                ref_manifest_path = root / "references" / "reference-set-a" / "screen-manifest.json"
                ref_manifest = json.loads(ref_manifest_path.read_text(encoding="utf-8"))
                ref_manifest["artifacts"][0][field] = value
                ref_manifest_path.write_text(json.dumps(ref_manifest), encoding="utf-8")

                errors: list[str] = []
                report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any(expected_error in error for error in errors), errors)

    def test_v2_requires_shell_binding_for_ui_patterns_0_3_1_and_preserves_0_3_0(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "legacy-package"
            root.mkdir()
            self._write_v2_package(root)

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "pass", errors)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool.pop("template_set_version")
            pool_path.write_text(json.dumps(pool), encoding="utf-8")
            errors = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "pass", errors)

        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "new-package"
            root.mkdir()
            self._write_v2_package(
                root,
                template_set_version="0.3.1",
                revision="36e0ce1191a0b53797d4c9f03eb945aae3f29bc7",
            )

            errors = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("shell_binding обязателен" in error for error in errors), errors)

            self._add_shell_bindings(root)
            errors = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "pass", errors)

    def test_v2_requires_shell_candidates_and_matching_pool_provenance(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(
                root,
                template_set_version="0.3.1",
                revision="36e0ce1191a0b53797d4c9f03eb945aae3f29bc7",
            )
            self._add_shell_bindings(root)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][0]["viewport_candidates"][0].pop("screen_shell_candidates")
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("screen_shell_candidates обязателен" in error for error in errors), errors)

            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][0]["viewport_candidates"][0]["screen_shell_candidates"] = [
                {
                    "status": "selected",
                    "catalog_url": "https://example.invalid/shell-catalog.git",
                    "catalog_revision": "1" * 40,
                    "shell_id": "shell.desktop.landscape",
                    "shell_version": "1.0.0",
                    "shell_viewport": {
                        "width": 1280,
                        "height": 720,
                        "unit": "css-px",
                        "orientation": "landscape",
                    },
                    "rationale": "Synthetic selected shell candidate.",
                }
            ]
            pool["template_set_version"] = "0.3.2"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")
            errors = []
            report = ui_reference.validate_package(root, errors)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("template_set_version в UI manifest и screen pool" in error for error in errors), errors)

    def test_v2_allows_multiple_proposed_shells_but_only_one_selected(self) -> None:
        viewport = {
            "status": "confirmed",
            "width": 1280,
            "height": 720,
            "unit": "css-px",
            "orientation": "landscape",
            "screen_shell_candidates": [],
        }
        for shell_id in ("shell.desktop.primary", "shell.desktop.alternative"):
            viewport["screen_shell_candidates"].append(
                {
                    "status": "proposed",
                    "catalog_url": "https://example.invalid/shell-catalog.git",
                    "catalog_revision": "1" * 40,
                    "shell_id": shell_id,
                    "shell_version": "1.0.0",
                    "shell_viewport": {
                        "width": 1280,
                        "height": 720,
                        "unit": "css-px",
                        "orientation": "landscape",
                    },
                    "rationale": "Synthetic proposed shell candidate.",
                }
            )

        errors: list[str] = []
        ui_reference._validate_shell_candidates(viewport, "viewport", errors, required=True)
        self.assertEqual(errors, [])

        for candidate in viewport["screen_shell_candidates"]:
            candidate["status"] = "selected"
        errors = []
        ui_reference._validate_shell_candidates(viewport, "viewport", errors, required=True)
        self.assertTrue(any("не более одной оболочки со статусом selected" in error for error in errors), errors)

    def test_v2_rejects_shell_binding_that_does_not_match_pool_candidate(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(
                root,
                template_set_version="0.3.1",
                revision="36e0ce1191a0b53797d4c9f03eb945aae3f29bc7",
            )
            self._add_shell_bindings(root)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][0]["viewport_candidates"][0]["screen_shell_candidates"][0]["shell_id"] = "shell.other"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("не совпадает с кандидатом selected" in error for error in errors), errors)

    def test_v2_rejects_shell_binding_viewport_drift_and_floating_revision(self) -> None:
        for mutation, expected_error in (
            ("viewport", "shell_viewport.width не совпадает"),
            ("revision", "catalog_revision должен быть закреплённой ревизией"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
                root = Path(temporary) / "ui-package"
                root.mkdir()
                self._write_v2_package(
                    root,
                    template_set_version="0.3.1",
                    revision="36e0ce1191a0b53797d4c9f03eb945aae3f29bc7",
                )
                self._add_shell_bindings(root)
                reference_manifest_path = root / "references" / "reference-set-a" / "screen-manifest.json"
                reference_manifest = json.loads(reference_manifest_path.read_text(encoding="utf-8"))
                if mutation == "viewport":
                    reference_manifest["artifacts"][0]["shell_binding"]["shell_viewport"]["width"] = 1440
                else:
                    reference_manifest["artifacts"][0]["shell_binding"]["catalog_revision"] = "main"
                reference_manifest_path.write_text(json.dumps(reference_manifest), encoding="utf-8")

                errors: list[str] = []
                report = ui_reference.validate_package(root, errors)

                self.assertEqual(report["status"], "fail")
                self.assertTrue(any(expected_error in error for error in errors), errors)

    def test_v2_confirmed_track_integrated_screen_requires_resolved_shell_status(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(
                root,
                template_set_version="0.3.1",
                revision="36e0ce1191a0b53797d4c9f03eb945aae3f29bc7",
            )
            self._add_shell_bindings(root, status="proposed")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("требует selected shell_binding" in error for error in errors), errors)

    def test_shell_binding_gap_and_not_applicable_shapes(self) -> None:
        viewport = {
            "viewport_id": "mobile-portrait",
            "width": 412,
            "height": 914,
            "unit": "css-px",
            "orientation": "portrait",
        }
        bindings = (
            {
                "status": "proposed",
                "catalog_url": "https://example.invalid/shell-catalog.git",
                "catalog_revision": "1" * 40,
                "shell_id": "shell.mobile.portrait",
                "shell_version": "1.0.0",
                "viewport_id": "mobile-portrait",
                "shell_viewport": {
                    "width": 412,
                    "height": 914,
                    "unit": "css-px",
                    "orientation": "portrait",
                },
                "rationale": "Нужно подтверждение разработчика.",
            },
            {
                "status": "gap",
                "viewport_id": "mobile-portrait",
                "reason": "Подходящая оболочка не найдена.",
                "decision_needed": "Уточнить каталог оболочек.",
            },
            {
                "status": "not_applicable",
                "rationale": "Результат не является визуальным экраном.",
            },
        )
        for binding in bindings:
            with self.subTest(status=binding["status"]):
                errors: list[str] = []
                ui_reference._validate_shell_binding(
                    {"viewport": viewport, "shell_binding": binding},
                    "artifact",
                    errors,
                    required=True,
                )
                self.assertEqual(errors, [])

    def test_shell_candidates_gap_not_applicable_and_exact_viewport_rules(self) -> None:
        cases = (
            (
                {
                    "status": "gap",
                    "screen_shell_candidates": [
                        {
                            "status": "gap",
                            "reason": "Размер области просмотра неизвестен.",
                            "decision_needed": "Уточнить viewport и каталог оболочек.",
                        }
                    ],
                },
                [],
            ),
            (
                {
                    "status": "not_applicable",
                    "screen_shell_candidates": [
                        {
                            "status": "not_applicable",
                            "rationale": "Интерфейс не является визуальным.",
                        }
                    ],
                },
                [],
            ),
            (
                {
                    "status": "proposed",
                    "width": 412,
                    "height": 914,
                    "unit": "css-px",
                    "orientation": "portrait",
                    "screen_shell_candidates": [
                        {
                            "status": "selected",
                            "catalog_url": "https://example.invalid/shell-catalog.git",
                            "catalog_revision": "1" * 40,
                            "shell_id": "shell.mobile.portrait",
                            "shell_version": "1.0.0",
                            "shell_viewport": {
                                "width": 412,
                                "height": 914,
                                "unit": "css-px",
                                "orientation": "portrait",
                            },
                            "rationale": "Synthetic candidate for validation.",
                        }
                    ],
                },
                ["selected допускается только для confirmed viewport"],
            ),
            (
                {
                    "status": "confirmed",
                    "width": 412,
                    "height": 914,
                    "unit": "css-px",
                    "orientation": "portrait",
                    "screen_shell_candidates": [
                        {
                            "status": "proposed",
                            "catalog_url": "https://example.invalid/shell-catalog.git",
                            "catalog_revision": "1" * 40,
                            "shell_id": "shell.mobile.portrait",
                            "shell_version": "1.0.0",
                            "shell_viewport": {
                                "width": 914,
                                "height": 412,
                                "unit": "css-px",
                                "orientation": "landscape",
                            },
                            "rationale": "Synthetic mismatched candidate.",
                        }
                    ],
                },
                ["shell_viewport.width не совпадает", "shell_viewport.orientation не совпадает"],
            ),
        )
        for viewport, expected_errors in cases:
            with self.subTest(status=viewport["status"]):
                errors: list[str] = []
                ui_reference._validate_shell_candidates(viewport, "viewport", errors, required=True)
                for expected in expected_errors:
                    self.assertTrue(any(expected in error for error in errors), errors)
                if not expected_errors:
                    self.assertEqual(errors, [])

    def test_v2_rejects_unlinked_artifact_id_and_unsafe_artifact_path(self) -> None:
        mutations = (
            ("link", "missing-artifact", "artifact_id"),
            ("path", "../outside.html", "границы UI-пакета"),
        )
        for mutation, value, expected_error in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
                root = Path(temporary) / "ui-package"
                root.mkdir()
                self._write_v2_package(root)
                if mutation == "link":
                    manifest_path = root / "манифест-спецификации-интерфейса.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["screens"][0]["reference_artifacts"] = [value]
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                else:
                    reference_manifest_path = root / "references" / "reference-set-a" / "screen-manifest.json"
                    reference_manifest = json.loads(reference_manifest_path.read_text(encoding="utf-8"))
                    reference_manifest["artifacts"][0]["path"] = value
                    reference_manifest_path.write_text(json.dumps(reference_manifest), encoding="utf-8")

                errors: list[str] = []
                report = ui_reference.validate_package(root, errors)

                self.assertEqual(report["status"], "fail")
                self.assertTrue(any(expected_error in error for error in errors), errors)

    def test_v2_requires_traceability_for_confirmed_track_integrated_screen(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            manifest_path = root / "манифест-спецификации-интерфейса.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["traceability"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("отсутствует запись traceability" in error for error in errors))

    def test_v2_rejects_status_drift_between_package_and_pool(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            manifest_path = root / "манифест-спецификации-интерфейса.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "proposed"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("status UI manifest и screen pool не совпадает" in error for error in errors))

    def test_v2_rejects_unknown_fields_and_duplicate_reference_ids(self) -> None:
        mutations = (
            ("unknown-field", "неизвестное поле"),
            ("duplicate-reference", "повторный identifier"),
        )
        for mutation, expected_error in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
                root = Path(temporary) / "ui-package"
                root.mkdir()
                self._write_v2_package(root)
                manifest_path = root / "манифест-спецификации-интерфейса.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if mutation == "unknown-field":
                    manifest["unexpected"] = True
                else:
                    manifest["screens"][0]["pattern_refs"].append("ui.pattern.shared")
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                errors: list[str] = []
                report = ui_reference.validate_package(root, errors)

                self.assertEqual(report["status"], "fail")
                self.assertTrue(any(expected_error in error for error in errors), errors)

    def test_v2_rejects_mismatched_viewport_dimensions(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            ref_manifest_path = root / "references" / "reference-set-a" / "screen-manifest.json"
            ref_manifest = json.loads(ref_manifest_path.read_text(encoding="utf-8"))
            ref_manifest["artifacts"][0]["viewport"]["width"] = 1440
            ref_manifest_path.write_text(json.dumps(ref_manifest), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("viewport.width не совпадает" in error for error in errors))

    def test_v2_track_integrated_rejects_unconfirmed_viewport_for_confirmed_screen(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["screens"][0]["viewport_candidates"][0]["status"] = "proposed"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("неподтверждённый viewport" in error for error in errors))

    def test_v2_requires_target_when_one_file_maps_to_multiple_views(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            ref_manifest_path = root / "references" / "reference-set-a" / "screen-manifest.json"
            ref_manifest = json.loads(ref_manifest_path.read_text(encoding="utf-8"))
            ref_manifest["artifacts"][1]["path"] = ref_manifest["artifacts"][0]["path"]
            ref_manifest_path.write_text(json.dumps(ref_manifest), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("требует target" in error for error in errors))

    def test_early_v2_package_may_have_open_traceability_and_no_prototype(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)
            manifest_path = root / "манифест-спецификации-интерфейса.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["workflow_mode"] = "early-prototype"
            manifest["status"] = "proposed"
            manifest["screens"] = [
                {**screen, "status": "proposed", "reference_artifacts": []}
                for screen in manifest["screens"]
            ]
            manifest["reference_sets"] = []
            manifest["traceability"] = [{"screen_id": "screen-a"}]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["workflow_mode"] = "early-prototype"
            pool["status"] = "proposed"
            for screen in pool["screens"]:
                screen["status"] = "proposed"
                screen["viewport_candidates"] = [
                    {
                        "viewport_id": "viewport-gap",
                        "status": "gap",
                        "rationale": "Размеры ещё не определены",
                        "source_refs": [],
                    }
                ]
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "pass", errors)
            self.assertEqual(errors, [])

    def test_early_v2_package_cannot_claim_confirmed_package_status(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root, workflow_mode="early-prototype")
            manifest_path = root / "манифест-спецификации-интерфейса.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "confirmed"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            pool_path = root / "пул-экранов.json"
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
            pool["status"] = "confirmed"
            pool_path.write_text(json.dumps(pool), encoding="utf-8")

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("early-prototype должен иметь status=proposed" in error for error in errors))

    def test_cli_validates_complete_v2_package(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_v2_package(root)

            result = subprocess.run(
                [sys.executable, str(TOOL_DIR / "ui_reference.py"), "validate", "--package", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"status": "pass"', result.stdout)

    def test_validate_package_rejects_candidate_and_unknown_template(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_valid_package(root)
            pool = json.loads((root / "пул-экранов.json").read_text(encoding="utf-8"))
            pool["screens"][0]["pattern_candidates"][0]["status"] = "candidate"
            (root / "пул-экранов.json").write_text(json.dumps(pool), encoding="utf-8")
            manifest = json.loads(
                (root / "манифест-спецификации-интерфейса.json").read_text(encoding="utf-8")
            )
            manifest["screens"][0]["template_refs"] = ["template.unknown"]
            (root / "манифест-спецификации-интерфейса.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("candidate" in error for error in errors))
            self.assertTrue(any("identifier" in error for error in errors))

    def test_validate_package_rejects_incomplete_traceability_and_escape(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_valid_package(root)
            manifest = json.loads(
                (root / "манифест-спецификации-интерфейса.json").read_text(encoding="utf-8")
            )
            manifest["screens"][0]["specification"] = "../outside.md"
            manifest["traceability"][0]["scenario_refs"] = []
            (root / "манифест-спецификации-интерфейса.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (root / "README.md").unlink()

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("обязательный файл" in error for error in errors))
            self.assertTrue(any("выходит за границы" in error for error in errors))
            self.assertTrue(any("scenario_refs" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
