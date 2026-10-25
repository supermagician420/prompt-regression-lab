import json
import tempfile
import unittest
from pathlib import Path

from prompt_regression import (
    Case,
    DataError,
    check,
    evaluate,
    load_cases,
    load_outputs,
    render_report,
)


class CaseTests(unittest.TestCase):
    def test_load_cases_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.jsonl"
            outputs_path = Path(tmp) / "outputs.jsonl"
            cases_path.write_text(
                json.dumps(
                    {
                        "id": "greeting",
                        "prompt": "Say hello",
                        "must_contain": ["hello"],
                        "must_not_contain": ["as an AI"],
                        "max_chars": 80,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            outputs_path.write_text(
                json.dumps({"id": "greeting", "output": "hello there"}) + "\n",
                encoding="utf-8",
            )
            cases = load_cases(str(cases_path))
            outputs = load_outputs(str(outputs_path))
        self.assertEqual(len(cases), 1)
        self.assertEqual(outputs["greeting"], "hello there")

    def test_duplicate_case_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            row = json.dumps({"id": "x", "prompt": "p"}) + "\n"
            path.write_text(row + row, encoding="utf-8")
            with self.assertRaises(DataError) as ctx:
                load_cases(str(path))
        self.assertIn("duplicate case id", str(ctx.exception))

    def test_bad_json_reports_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(
                json.dumps({"id": "ok", "prompt": "p"}) + "\nnot-json\n",
                encoding="utf-8",
            )
            with self.assertRaises(DataError) as ctx:
                load_cases(str(path))
        self.assertIn(":2:", str(ctx.exception))


class CheckTests(unittest.TestCase):
    def test_perfect_output_passes(self) -> None:
        case = Case("x", "p", ("hello",), ("as an AI",), 30)
        result = check(case, "hello, how can I help?")
        self.assertTrue(result.passed)
        self.assertEqual(result.failures, ())

    def test_missing_phrase_fails(self) -> None:
        case = Case("x", "p", ("hello", "world"))
        result = check(case, "hello")
        self.assertFalse(result.passed)
        self.assertTrue(any("world" in failure for failure in result.failures))

    def test_forbidden_phrase_fails(self) -> None:
        case = Case("x", "p", (), ("as an AI",))
        result = check(case, "As an AI, I cannot.")
        self.assertFalse(result.passed)

    def test_too_long_fails(self) -> None:
        case = Case("x", "p", max_chars=5)
        result = check(case, "six characters")
        self.assertFalse(result.passed)
        self.assertTrue(any("too long" in failure for failure in result.failures))

    def test_empty_output_fails(self) -> None:
        result = check(Case("x", "p"), "   ")
        self.assertFalse(result.passed)

    def test_missing_output_fails(self) -> None:
        results = evaluate([Case("x", "p")], {})
        self.assertFalse(results[0].passed)
        self.assertIn("missing output", results[0].failures[0])


class ReportTests(unittest.TestCase):
    def test_report_has_summary_and_failure_detail(self) -> None:
        results = [
            check(Case("good", "p", ("hello",)), "hello"),
            check(Case("bad", "p", ("hello",)), "bye"),
        ]
        report = render_report(results)
        self.assertIn("1/2", report)
        self.assertIn("## Failure detail", report)
        self.assertIn("### bad", report)
        self.assertIn("missing: hello", report)


if __name__ == "__main__":
    unittest.main()
