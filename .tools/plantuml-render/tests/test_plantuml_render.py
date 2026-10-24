import io
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

import plantuml_render  # noqa: E402


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.content


class RendererSymlinkTests(unittest.TestCase):
    def make_symlink(self, target: Path, link: Path, *, is_directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=is_directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

    def test_input_path_guard_rejects_windows_reparse_point_metadata(self) -> None:
        path = Path("junction")
        metadata = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=metadata):
            self.assertTrue(plantuml_render.path_has_symlink_component(path))

    def test_input_symlink_is_rejected_before_endpoint_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "private.plantuml"
            outside.write_text("@startuml\nprivate\n@enduml\n", encoding="utf-8")
            link = base / "diagram.plantuml"
            self.make_symlink(outside, link)
            request = Mock()
            stderr = io.StringIO()

            with patch.object(plantuml_render, "urlopen", request), redirect_stderr(stderr):
                result = plantuml_render.render_file(
                    link, "plantuml", "https://kroki.invalid", None, timeout=1
                )

            self.assertEqual(result, 1)
            request.assert_not_called()
            self.assertEqual(plantuml_render.find_diagram_files(link, "auto"), [])

    def test_input_under_symlink_parent_is_rejected_before_endpoint_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            source = outside / "private.plantuml"
            source.write_text("@startuml\nprivate\n@enduml\n", encoding="utf-8")
            link_dir = base / "linked-diagrams"
            self.make_symlink(outside, link_dir, is_directory=True)
            linked_source = link_dir / source.name
            request = Mock()
            stderr = io.StringIO()

            with patch.object(plantuml_render, "urlopen", request), redirect_stderr(stderr):
                result = plantuml_render.render_file(
                    linked_source, "plantuml", "https://kroki.invalid", None, timeout=1
                )

            self.assertEqual(result, 1)
            request.assert_not_called()
            self.assertEqual(plantuml_render.find_diagram_files(linked_source, "auto"), [])

    def test_output_under_symlink_parent_is_rejected_without_changing_referent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            output = outside / "diagram.png"
            output.write_bytes(b"preserve me")
            link_dir = base / "linked-output"
            self.make_symlink(outside, link_dir, is_directory=True)

            with self.assertRaises(ValueError):
                plantuml_render.write_output(link_dir / output.name, b"overwrite")

            self.assertEqual(output.read_bytes(), b"preserve me")

    def test_output_symlink_is_rejected_without_changing_referent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "diagram.plantuml"
            source.write_text("@startuml\nA -> B\n@enduml\n", encoding="utf-8")
            outside = base / "user-data.bin"
            outside.write_bytes(b"preserve me")
            self.make_symlink(outside, source.with_suffix(".png"))
            request = Mock()
            stderr = io.StringIO()

            with patch.object(plantuml_render, "urlopen", request), redirect_stderr(stderr):
                result = plantuml_render.render_file(
                    source, "plantuml", "https://kroki.invalid", None, timeout=1
                )

            self.assertEqual(result, 1)
            request.assert_not_called()
            self.assertEqual(outside.read_bytes(), b"preserve me")

    def test_existing_regular_output_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "diagram.plantuml"
            source.write_text("@startuml\nA -> B\n@enduml\n", encoding="utf-8")
            output = source.with_suffix(".png")
            output.write_bytes(b"old")
            stderr = io.StringIO()

            with patch.object(plantuml_render, "urlopen", return_value=FakeResponse(b"new")), redirect_stderr(stderr):
                result = plantuml_render.render_file(
                    source, "plantuml", "https://kroki.invalid", None, timeout=1
                )

            self.assertEqual(result, 0)
            self.assertEqual(output.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
