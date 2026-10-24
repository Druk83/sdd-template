import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PDD_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PDD_DIR))

import pdd_scan  # noqa: E402


class ScanHiddenDirectoriesTests(unittest.TestCase):
    def test_includes_repository_tools_and_skips_other_hidden_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".tools" / "nested").mkdir(parents=True)
            for hidden_dir in (".agents", ".git", ".manifest", ".tasks", ".private"):
                (root / hidden_dir).mkdir()

            task_path = root / ".tasks" / "fixture.md"
            task_path.write_text("task fixture", encoding="utf-8")
            marker = "@" + "todo #SCAN-TEST:15m fixture marker\n# refs: .tasks/fixture.md\n"
            (root / ".tools" / "catalog.py").write_text(marker, encoding="utf-8")
            (root / ".tools" / "nested" / "nested.py").write_text(
                "@" + "todo #NESTED-TEST:15m nested marker\n", encoding="utf-8"
            )
            for hidden_dir in (".agents", ".git", ".manifest", ".tasks", ".private"):
                (root / hidden_dir / "ignored.py").write_text(
                    "@" + "todo #HIDDEN-TEST:15m hidden marker\n", encoding="utf-8"
                )

            with mock.patch("pdd_scan.os.getcwd", return_value=str(root)):
                items = pdd_scan.scan(str(root))

        self.assertEqual(
            {item["task_id"] for item in items},
            {"SCAN-TEST", "NESTED-TEST"},
        )
        self.assertTrue(next(item for item in items if item["task_id"] == "SCAN-TEST")["refs_exist"])

    def test_does_not_include_nested_tools_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested_tools = root / "src" / ".tools"
            nested_tools.mkdir(parents=True)
            (nested_tools / "ignored.py").write_text(
                "@" + "todo #NESTED-TOOLS:15m nested marker\n", encoding="utf-8"
            )

            items = pdd_scan.scan(str(root))

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
