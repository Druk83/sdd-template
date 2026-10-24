import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


TOOL_DIR = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(TOOL_DIR))

import ui_screen_scaffold  # noqa: E402


class ScreenScaffoldTests(unittest.TestCase):
    def test_tool_version_and_registry_paths_match(self) -> None:
        readme = (TOOL_DIR / "README.md").read_text(encoding="utf-8")
        registry_path = SOURCE_ROOT / ".tools" / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        entry = next(item for item in registry if item["name"] == "ui-screen-scaffold")
        version_match = re.search(r"Версия инструмента: `([0-9]+\.[0-9]+\.[0-9]+)`", readme)
        if version_match is None:
            self.fail("Версия инструмента не найдена в README")
        self.assertEqual(entry["version"], version_match.group(1))
        self.assertTrue((SOURCE_ROOT / entry["path"]).is_file())
        self.assertTrue((SOURCE_ROOT / ".tools" / "ui-screen-scaffold" / "ui-screen-scaffold.bat").is_file())

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = self.root / "project" / "docs" / "requirements" / "пользовательский-интерфейс"
        self.framework = self.root / "framework"
        self.reference_root = self.package / "references" / "reference-set-a"
        self.package.mkdir(parents=True)
        self.reference_root.mkdir(parents=True)
        self.commit = "a" * 40

        source_library_path = SOURCE_ROOT / ".tools" / "ui-screen-scaffold" / "shells" / "shell-library.json"
        source_library = json.loads(source_library_path.read_text(encoding="utf-8"))
        self.shell = next(
            item for item in source_library["shells"]
            if item["shell_id"] == "shell-pixel-412x915-portrait"
        )
        shell_root = self.framework / ".tools" / "ui-screen-scaffold" / "shells"
        shell_root.mkdir(parents=True)
        shell_page_source = source_library_path.parent / self.shell["path"]
        shell_page_target = shell_root / self.shell["path"]
        shell_page_target.parent.mkdir(parents=True)
        shutil.copyfile(shell_page_source, shell_page_target)
        shutil.copyfile(source_library_path.parent / "shell.css", shell_root / "shell.css")
        (shell_root / "shell-library.json").write_text(
            json.dumps({"schema_version": "1.0", "shells": [self.shell]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.framework / "release-manifest.json").write_text(
            json.dumps({"package_id": "sdd-template", "source_commit": self.commit}),
            encoding="utf-8",
        )
        self._write_package()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _validate_package(self) -> subprocess.CompletedProcess[str]:
        validator = SOURCE_ROOT / ".tools" / "ui-reference" / "ui_reference.py"
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(validator),
                "validate",
                "--package",
                str(self.package),
                "--framework-root",
                str(self.framework),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def _write_package(self, workflow_mode: str = "track-integrated", shell_status: str = "selected") -> None:
        shell_binding = {
            "status": shell_status,
            "catalog_url": ui_screen_scaffold.FRAMEWORK_URL,
            "catalog_revision": self.commit,
            "shell_id": self.shell["shell_id"],
            "shell_version": self.shell["shell_version"],
            "viewport_id": self.shell["viewport_id"],
            "shell_viewport": {
                "width": self.shell["width"],
                "height": self.shell["height"],
                "unit": self.shell["unit"],
                "orientation": self.shell["orientation"],
            },
        }
        if shell_status == "proposed":
            shell_binding["rationale"] = "Требуется подтверждение разработчика."
        if shell_status == "gap":
            shell_binding = {
                "status": "gap",
                "viewport_id": self.shell["viewport_id"],
                "reason": "Подходящая оболочка не подтверждена.",
                "decision_needed": "Подтвердить оболочку.",
            }

        viewport_status = "confirmed" if shell_status == "selected" else "proposed"
        screen_status = "confirmed" if workflow_mode == "track-integrated" and shell_status == "selected" else "proposed"
        manifest_status = "confirmed" if workflow_mode == "track-integrated" else "proposed"
        candidate = {**shell_binding}
        if shell_status == "gap":
            candidate.pop("viewport_id", None)
        else:
            candidate.pop("viewport_id", None)
            if shell_status == "selected":
                candidate["rationale"] = "Стандартная оболочка подходит выбранному viewport."

        screen_pool = {
            "schema_version": "2.0",
            "contract_version": "2",
            "workflow_mode": workflow_mode,
            "template_set_version": "0.3.1",
            "status": manifest_status,
            "source_refs": ["SRC-1"],
            "screens": [
                {
                    "screen_id": "screen-a",
                    "title": "Экран A",
                    "screen_type": "dashboard",
                    "purpose": "Отобразить состояние проекта.",
                    "user_roles": ["operator"],
                    "user_task": "Просмотреть состояние.",
                    "pattern_candidates": [
                        {"pattern_id": "pattern.dashboard", "status": "selected", "rationale": "Подходит."}
                    ],
                    "template_candidates": [
                        {"template_id": "template.dashboard", "status": "selected", "rationale": "Подходит."}
                    ],
                    "states": ["initial"],
                    "transitions": [],
                    "viewport_candidates": [
                        {
                            "viewport_id": self.shell["viewport_id"],
                            "width": self.shell["width"],
                            "height": self.shell["height"],
                            "unit": self.shell["unit"],
                            "orientation": self.shell["orientation"],
                            "status": viewport_status,
                            "rationale": "Подтверждённый тестовый viewport.",
                            "responsive_profile": "compact-mobile",
                            "breakpoint_conditions": "Фиксированная тестовая область просмотра.",
                            "purpose": "reference",
                            "source": "test-fixture:viewport",
                            "screen_shell_candidates": [candidate],
                        }
                    ],
                    "source_refs": ["SRC-1"],
                    "status": screen_status,
                }
            ],
        }
        manifest_screen = {
            "screen_id": "screen-a",
            "specification": "screens/screen-a.md",
            "status": screen_status,
            "pattern_refs": ["pattern.dashboard"],
            "template_refs": ["template.dashboard"],
            "reference_artifacts": ["artifact-a"],
        }
        manifest = {
            "schema_version": "2.0",
            "contract_version": "2",
            "workflow_mode": workflow_mode,
            "template_set_version": "0.3.1",
            "source_url": ui_screen_scaffold.UI_PATTERNS_URL,
            "revision": "b" * 40,
            "status": manifest_status,
            "screen_pool": "пул-экранов.json",
            "screens": [manifest_screen],
            "reference_sets": [
                {"reference_set_id": "reference-set-a", "path": "references/reference-set-a"}
            ],
            "traceability": [
                {
                    "screen_id": "screen-a",
                    "requirement_refs": ["REQ-1"],
                    "scenario_refs": ["SCN-1"],
                    "acceptance_criteria": ["AC-1"],
                }
            ] if workflow_mode == "track-integrated" else [],
            "gaps": [],
        }
        (self.package / "README.md").write_text("UI package\n", encoding="utf-8")
        specifications = self.package / "screens"
        specifications.mkdir(exist_ok=True)
        (specifications / "screen-a.md").write_text("# Screen A\n", encoding="utf-8")
        artifact = {
            "artifact_id": "artifact-a",
            "screen_id": "screen-a",
            "role": "operator",
            "state": "initial",
            "viewport": {
                "viewport_id": self.shell["viewport_id"],
                "width": self.shell["width"],
                "height": self.shell["height"],
                "unit": self.shell["unit"],
                "orientation": self.shell["orientation"],
            },
            "path": f"screens/screen-a/{self.shell['viewport_id']}/index.html",
            "pattern_refs": ["pattern.dashboard"],
            "template_refs": ["template.dashboard"],
            "shell_binding": shell_binding,
        }
        screen_manifest = {
            "schema_version": "2.0",
            "contract_version": "2",
            "reference_set_id": "reference-set-a",
            "template_set_version": "0.3.1",
            "source_url": ui_screen_scaffold.UI_PATTERNS_URL,
            "revision": "b" * 40,
            "artifacts": [artifact],
        }
        (self.package / "пул-экранов.json").write_text(json.dumps(screen_pool), encoding="utf-8")
        (self.package / "манифест-спецификации-интерфейса.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (self.reference_root / "screen-manifest.json").write_text(
            json.dumps(screen_manifest), encoding="utf-8"
        )

    def _build(self) -> dict[str, Any]:
        return ui_screen_scaffold.build_plan(self.package, "reference-set-a", self.framework)

    def test_default_plan_is_read_only_and_uses_selected_shell(self) -> None:
        plan = self._build()
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(len(plan["outputs"]), 1)
        self.assertEqual(len(plan["files"]), 4)
        self.assertFalse((self.reference_root / "screens").exists())

    def test_selected_catalog_viewports_resolve_through_shell_binding(self) -> None:
        source_library_path = SOURCE_ROOT / ".tools" / "ui-screen-scaffold" / "shells" / "shell-library.json"
        source_library = json.loads(source_library_path.read_text(encoding="utf-8"))
        selected_ids = {
            "shell-deviceatlas-mobile-375x812-portrait",
            "shell-ipad-mini-768x1024-portrait",
            "shell-pixel-9-pro-fold-cover-444x995-portrait",
            "shell-pixel-9-pro-fold-inner-755x783-portrait",
            "shell-desktop-800x600",
            "shell-desktop-1520x700",
            "shell-desktop-1920x920",
            "shell-desktop-1920x960",
            "shell-desktop-1920x1080",
            "shell-desktop-2560x1280",
        }
        shells_by_id = {item["shell_id"]: item for item in source_library["shells"]}
        shell_root = self.framework / ".tools" / "ui-screen-scaffold" / "shells"
        local_library_path = shell_root / "shell-library.json"

        for shell_id in sorted(selected_ids):
            with self.subTest(shell_id=shell_id):
                self.shell = shells_by_id[shell_id]
                shell_page = shell_root / self.shell["path"]
                shell_page.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_library_path.parent / self.shell["path"], shell_page)
                local_library_path.write_text(
                    json.dumps({"schema_version": "1.0", "shells": [self.shell]}, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._write_package()

                plan = self._build()
                self.assertEqual(plan["status"], "ready")
                ui_screen_scaffold.write_plan(plan)
                result = self._validate_package()
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertEqual(json.loads(result.stdout)["status"], "pass")

                generated = self.reference_root / "screens"
                if generated.exists():
                    shutil.rmtree(generated)

    def test_write_creates_independent_preview_and_traceability(self) -> None:
        plan = self._build()
        written = ui_screen_scaffold.write_plan(plan)
        self.assertEqual(len(written), 4)
        output = self.reference_root / "screens" / "screen-a" / self.shell["viewport_id"]
        page = (output / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="shell.css"', page)
        self.assertIn('rel="icon" href="data:,"', page)
        self.assertIn('data-screen-id="screen-a"', page)
        self.assertIn(
            '<body data-reference-artifact="true" '
            'style="--viewport-width: 412px; --viewport-height: 915px">',
            page,
        )
        self.assertIn('data-slot-id="screen-content"', page)
        self.assertIn(f'--viewport-width: {self.shell["width"]}px', page)
        css = (output / "shell.css").read_text(encoding="utf-8")
        self.assertIn('body[data-reference-artifact="true"]', css)
        self.assertIn("display: none", css)
        local_manifest = json.loads((output / "reference-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(local_manifest["shell_binding"]["shell_id"], self.shell["shell_id"])
        self.assertEqual(local_manifest["ui_patterns"]["pattern_refs"], ["pattern.dashboard"])
        result = self._validate_package()
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "pass", report)

    def test_multiple_screens_generate_independent_portrait_and_landscape_pages(self) -> None:
        source_library_path = SOURCE_ROOT / ".tools" / "ui-screen-scaffold" / "shells" / "shell-library.json"
        source_library = json.loads(source_library_path.read_text(encoding="utf-8"))
        landscape_shell = next(
            item for item in source_library["shells"]
            if item["shell_id"] == "shell-pixel-915x412-landscape"
        )
        local_library_path = self.framework / ".tools" / "ui-screen-scaffold" / "shells" / "shell-library.json"
        local_library = json.loads(local_library_path.read_text(encoding="utf-8"))
        local_library["shells"].append(landscape_shell)
        local_shell_root = local_library_path.parent
        landscape_page = local_shell_root / landscape_shell["path"]
        landscape_page.parent.mkdir(parents=True)
        shutil.copyfile(source_library_path.parent / landscape_shell["path"], landscape_page)
        local_library_path.write_text(json.dumps(local_library), encoding="utf-8")

        viewport = {
            "viewport_id": landscape_shell["viewport_id"],
            "width": landscape_shell["width"],
            "height": landscape_shell["height"],
            "unit": landscape_shell["unit"],
            "orientation": landscape_shell["orientation"],
            "status": "confirmed",
            "rationale": "Подтверждённый тестовый альбомный viewport.",
            "responsive_profile": "compact-mobile",
            "breakpoint_conditions": "Фиксированная тестовая область просмотра.",
            "purpose": "reference",
            "source": "test-fixture:landscape-viewport",
            "screen_shell_candidates": [
                {
                    "status": "selected",
                    "catalog_url": ui_screen_scaffold.FRAMEWORK_URL,
                    "catalog_revision": self.commit,
                    "shell_id": landscape_shell["shell_id"],
                    "shell_version": landscape_shell["shell_version"],
                    "shell_viewport": {
                        "width": landscape_shell["width"],
                        "height": landscape_shell["height"],
                        "unit": landscape_shell["unit"],
                        "orientation": landscape_shell["orientation"],
                    },
                    "rationale": "Тестовая оболочка соответствует альбомной геометрии.",
                }
            ],
        }
        pool_path = self.package / "пул-экранов.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        screen_b = json.loads(json.dumps(pool["screens"][0]))
        screen_b.update(
            {
                "screen_id": "screen-b",
                "title": "Экран B",
                "purpose": "Проверить самостоятельный макет в альбомной ориентации.",
                "states": ["review"],
                "viewport_candidates": [viewport],
            }
        )
        pool["screens"].append(screen_b)
        pool_path.write_text(json.dumps(pool), encoding="utf-8")
        (self.package / "screens" / "screen-b.md").write_text("# Screen B\n", encoding="utf-8")

        ui_manifest_path = self.package / "манифест-спецификации-интерфейса.json"
        ui_manifest = json.loads(ui_manifest_path.read_text(encoding="utf-8"))
        ui_manifest["screens"].append(
            {
                "screen_id": "screen-b",
                "specification": "screens/screen-b.md",
                "status": "confirmed",
                "pattern_refs": ["pattern.dashboard"],
                "template_refs": ["template.dashboard"],
                "reference_artifacts": ["artifact-b"],
            }
        )
        ui_manifest["traceability"].append(
            {
                "screen_id": "screen-b",
                "requirement_refs": ["REQ-2"],
                "scenario_refs": ["SCN-2"],
                "acceptance_criteria": ["AC-2"],
            }
        )
        ui_manifest_path.write_text(json.dumps(ui_manifest), encoding="utf-8")

        screen_manifest_path = self.reference_root / "screen-manifest.json"
        screen_manifest = json.loads(screen_manifest_path.read_text(encoding="utf-8"))
        artifact_b = json.loads(json.dumps(screen_manifest["artifacts"][0]))
        artifact_b.update(
            {
                "artifact_id": "artifact-b",
                "screen_id": "screen-b",
                "state": "review",
                "viewport": {
                    "viewport_id": landscape_shell["viewport_id"],
                    "width": landscape_shell["width"],
                    "height": landscape_shell["height"],
                    "unit": landscape_shell["unit"],
                    "orientation": landscape_shell["orientation"],
                },
                "path": f"screens/screen-b/{landscape_shell['viewport_id']}/index.html",
                "shell_binding": {
                    "status": "selected",
                    "catalog_url": ui_screen_scaffold.FRAMEWORK_URL,
                    "catalog_revision": self.commit,
                    "shell_id": landscape_shell["shell_id"],
                    "shell_version": landscape_shell["shell_version"],
                    "viewport_id": landscape_shell["viewport_id"],
                    "shell_viewport": {
                        "width": landscape_shell["width"],
                        "height": landscape_shell["height"],
                        "unit": landscape_shell["unit"],
                        "orientation": landscape_shell["orientation"],
                    },
                },
            }
        )
        screen_manifest["artifacts"].append(artifact_b)
        screen_manifest_path.write_text(json.dumps(screen_manifest), encoding="utf-8")

        plan = self._build()
        written = ui_screen_scaffold.write_plan(plan)
        self.assertEqual(len(plan["outputs"]), 2)
        self.assertEqual(len(written), 8)
        portrait_path = self.reference_root / "screens" / "screen-a" / self.shell["viewport_id"]
        landscape_path = self.reference_root / "screens" / "screen-b" / landscape_shell["viewport_id"]
        for output_path, shell in ((portrait_path, self.shell), (landscape_path, landscape_shell)):
            page = (output_path / "index.html").read_text(encoding="utf-8")
            self.assertIn(f'data-shell-id="{shell["shell_id"]}"', page)
            self.assertIn(f'--viewport-width: {shell["width"]}px', page)
            self.assertIn(f'--viewport-height: {shell["height"]}px', page)
            self.assertTrue((output_path / "reference-manifest.json").is_file())

        result = self._validate_package()
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "pass", report)

    def test_any_existing_target_blocks_all_writes(self) -> None:
        output = self.reference_root / "screens" / "screen-a" / self.shell["viewport_id"]
        output.mkdir(parents=True)
        (output / "shell.css").write_text("user data", encoding="utf-8")
        with self.assertRaisesRegex(ui_screen_scaffold.ScaffoldError, "Целевые файлы уже существуют"):
            self._build()
        self.assertFalse((output / "index.html").exists())
        self.assertEqual((output / "shell.css").read_text(encoding="utf-8"), "user data")

    def test_path_traversal_is_rejected(self) -> None:
        manifest_path = self.reference_root / "screen-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"][0]["path"] = "screens/../outside/index.html"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ui_screen_scaffold.ScaffoldError, "выходит за разрешённый каталог"):
            self._build()

    def test_absolute_windows_path_is_rejected(self) -> None:
        manifest_path = self.reference_root / "screen-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"][0]["path"] = "C:/outside/index.html"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ui_screen_scaffold.ScaffoldError, "выходит за разрешённый каталог"):
            self._build()

    def test_unknown_shell_version_is_rejected(self) -> None:
        manifest_path = self.reference_root / "screen-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"][0]["shell_binding"]["shell_version"] = "9.9.9"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ui_screen_scaffold.ScaffoldError, "не совпадает с кандидатом"):
            self._build()

    def test_library_geometry_is_authoritative(self) -> None:
        manifest_path = self.reference_root / "screen-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = manifest["artifacts"][0]
        artifact["viewport"]["width"] = 390
        artifact["shell_binding"]["shell_viewport"]["width"] = 390
        pool_path = self.package / "пул-экранов.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        viewport = pool["screens"][0]["viewport_candidates"][0]
        viewport["width"] = 390
        viewport["screen_shell_candidates"][0]["shell_viewport"]["width"] = 390
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pool_path.write_text(json.dumps(pool), encoding="utf-8")
        with self.assertRaisesRegex(ui_screen_scaffold.ScaffoldError, "не совпадает с выбранной привязкой"):
            self._build()

    def test_missing_pattern_decision_is_reported_as_gap(self) -> None:
        manifest_path = self.reference_root / "screen-manifest.json"
        reference_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reference_manifest["artifacts"][0]["pattern_refs"] = []
        manifest = json.loads((self.package / "манифест-спецификации-интерфейса.json").read_text(encoding="utf-8"))
        manifest["screens"][0]["pattern_refs"] = []
        manifest_path.write_text(json.dumps(reference_manifest), encoding="utf-8")
        (self.package / "манифест-спецификации-интерфейса.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        plan = self._build()
        self.assertEqual(plan["status"], "ready_with_gaps")
        self.assertTrue(any(gap.get("area") == "pattern_refs" for gap in plan["gaps"]))

    def test_track_integrated_rejects_proposed_shell(self) -> None:
        self._write_package(shell_status="proposed")
        with self.assertRaisesRegex(ui_screen_scaffold.ScaffoldError, "track-integrated требует selected"):
            self._build()

    def test_early_prototype_allows_proposed_shell(self) -> None:
        self._write_package(workflow_mode="early-prototype", shell_status="proposed")
        plan = self._build()
        self.assertEqual(plan["workflow_mode"], "early-prototype")
        self.assertEqual(plan["status"], "ready")

    def test_gap_is_reported_without_generating_a_shell(self) -> None:
        self._write_package(shell_status="gap")
        plan = self._build()
        self.assertEqual(plan["status"], "gap")
        self.assertEqual(plan["gaps"][0]["artifact_id"], "artifact-a")
        self.assertEqual(plan["_writes"], {})


if __name__ == "__main__":
    unittest.main()
