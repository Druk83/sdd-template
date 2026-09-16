import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

import ui_reference  # noqa: E402


class UiReferenceTests(unittest.TestCase):
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

    def test_validate_reference_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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

    def test_migration_does_not_overwrite_or_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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

    def test_validate_full_package_and_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ui-package"
            root.mkdir()
            self._write_valid_package(root)

            errors: list[str] = []
            report = ui_reference.validate_package(root, errors)

            self.assertEqual(report["status"], "pass")
            self.assertEqual(errors, [])

    def test_validate_package_rejects_candidate_and_unknown_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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
            self.assertTrue(any("неизвестный identifier" in error for error in errors))

    def test_validate_package_rejects_incomplete_traceability_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
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
