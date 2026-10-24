import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

from agent_logic import cli  # noqa: E402
from agent_logic.errors import InputError  # noqa: E402
from agent_logic.ingestion import SourceDocument  # noqa: E402
from agent_logic.structural_analysis import MAX_EXPRESSION_DEPTH, _Analyzer  # noqa: E402


class ExpressionDepthTests(unittest.TestCase):
    def make_analyzer(self) -> _Analyzer:
        document = SourceDocument(
            path=Path("requirements.md"),
            relative_path="requirements.md",
            text="",
            size_bytes=0,
            line_count=0,
            title=None,
        )
        return _Analyzer(document, 0)

    def test_ordinary_binary_expression_keeps_its_shape(self) -> None:
        analyzer = self.make_analyzer()

        expression_id = analyzer._parse_expression("alpha or beta", 1, [])

        self.assertIsNotNone(expression_id)
        self.assertEqual(analyzer.expressions[0]["operator"], "OR")
        self.assertEqual(len(analyzer.expressions[0]["operands"]), 2)

    def test_excessive_or_chain_raises_input_error(self) -> None:
        analyzer = self.make_analyzer()
        expression = " or ".join(f"condition-{index}" for index in range(MAX_EXPRESSION_DEPTH + 3))

        with self.assertRaisesRegex(InputError, "logical expression depth limit exceeded"):
            analyzer._parse_expression(expression, 1, [])

    def test_cli_reports_deep_expression_as_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "requirements.md"
            conditions = " or ".join(f"condition-{index}" for index in range(MAX_EXPRESSION_DEPTH + 3))
            input_path.write_text(f"The user must authenticate when {conditions}.\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = cli.run(["compile", str(input_path)])

            self.assertEqual(result, 1)
            self.assertIn("logical expression depth limit exceeded", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
