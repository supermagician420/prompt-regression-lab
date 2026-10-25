#!/usr/bin/env python3
"""Check model outputs against small, explicit prompt contracts.

The tool does not call an LLM by itself. You either:
  * run your model elsewhere and save outputs as JSONL, or
  * pass --command, which reads a prompt on stdin and writes an answer on stdout.
"""

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class DataError(ValueError):
    """The case or output file is malformed."""


@dataclass(frozen=True)
class Case:
    id: str
    prompt: str
    must_contain: Tuple[str, ...] = ()
    must_not_contain: Tuple[str, ...] = ()
    max_chars: Optional[int] = None


@dataclass(frozen=True)
class Result:
    case_id: str
    passed: bool
    output: str
    failures: Tuple[str, ...]


def _string_list(value: Any, field: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise DataError("%s must be a list of non-empty strings" % field)
    return tuple(value)


def _case_from_dict(raw: Dict[str, Any], where: str) -> Case:
    case_id = raw.get("id")
    prompt = raw.get("prompt")
    if not isinstance(case_id, str) or not case_id.strip():
        raise DataError("%s: id must be a non-empty string" % where)
    if not isinstance(prompt, str) or not prompt.strip():
        raise DataError("%s: prompt must be a non-empty string" % where)
    max_chars = raw.get("max_chars")
    if max_chars is not None and (not isinstance(max_chars, int) or max_chars <= 0):
        raise DataError("%s: max_chars must be a positive integer" % where)
    return Case(
        id=case_id.strip(),
        prompt=prompt,
        must_contain=_string_list(raw.get("must_contain"), "must_contain"),
        must_not_contain=_string_list(raw.get("must_not_contain"), "must_not_contain"),
        max_chars=max_chars,
    )


def _iter_jsonl(path: str) -> Iterable[Tuple[int, Dict[str, Any]]]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DataError("cannot read %s: %s" % (path, exc)) from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataError("%s:%d: invalid JSON: %s" % (path, line_number, exc.msg)) from exc
        if not isinstance(raw, dict):
            raise DataError("%s:%d: each line must be a JSON object" % (path, line_number))
        yield line_number, raw


def load_cases(path: str) -> List[Case]:
    cases: List[Case] = []
    seen = set()
    for line_number, raw in _iter_jsonl(path):
        case = _case_from_dict(raw, "%s:%d" % (path, line_number))
        if case.id in seen:
            raise DataError("%s:%d: duplicate case id %r" % (path, line_number, case.id))
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise DataError("%s: no cases found" % path)
    return cases


def load_outputs(path: str) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    for line_number, raw in _iter_jsonl(path):
        case_id = raw.get("id")
        output = raw.get("output")
        if not isinstance(case_id, str) or not case_id.strip():
            raise DataError("%s:%d: id must be a non-empty string" % (path, line_number))
        if not isinstance(output, str):
            raise DataError("%s:%d: output must be a string" % (path, line_number))
        if case_id in outputs:
            raise DataError("%s:%d: duplicate output id %r" % (path, line_number, case_id))
        outputs[case_id] = output
    if not outputs:
        raise DataError("%s: no outputs found" % path)
    return outputs


def check(case: Case, output: str) -> Result:
    failures: List[str] = []
    if not output.strip():
        failures.append("empty output")
    folded = output.casefold()
    for phrase in case.must_contain:
        if phrase.casefold() not in folded:
            failures.append("missing: %s" % phrase)
    for phrase in case.must_not_contain:
        if phrase.casefold() in folded:
            failures.append("forbidden: %s" % phrase)
    if case.max_chars is not None and len(output) > case.max_chars:
        failures.append("too long: %d > %d" % (len(output), case.max_chars))
    return Result(case.id, not failures, output, tuple(failures))


def evaluate(cases: Sequence[Case], outputs: Dict[str, str]) -> List[Result]:
    results: List[Result] = []
    for case in cases:
        if case.id not in outputs:
            results.append(Result(case.id, False, "", ("missing output for case",)))
        else:
            results.append(check(case, outputs[case.id]))
    return results


def run_command(command: str, prompt: str, timeout: float) -> str:
    """Run a model command without a shell; the prompt is sent on stdin."""
    argv = shlex.split(command)
    if not argv:
        raise DataError("--command is empty")
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DataError("model command failed: %s" % exc) from exc
    if proc.returncode != 0:
        raise DataError("model command exited %d: %s" % (proc.returncode, proc.stderr.strip()[:300]))
    return proc.stdout


def _cell(value: object, limit: int = 80) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def render_report(results: Sequence[Result]) -> str:
    passed = sum(1 for result in results if result.passed)
    lines = [
        "# Prompt Regression Report",
        "",
        "- Cases: %d" % len(results),
        "- Passed: %d/%d (%.1f%%)" % (passed, len(results), 100.0 * passed / len(results)),
        "",
        "| Case | Result | Output chars | Failures |",
        "| --- | :---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            "| %s | %s | %d | %s |"
            % (
                _cell(result.case_id, 40),
                "PASS" if result.passed else "FAIL",
                len(result.output),
                _cell(", ".join(result.failures) or "-", 160),
            )
        )
    failures = [result for result in results if not result.passed]
    lines.extend(["", "## Failure detail", ""])
    if not failures:
        lines.append("None.")
    else:
        for result in failures:
            lines.extend(
                [
                    "### %s" % result.case_id,
                    "",
                    "```text",
                    result.output[:2000] if result.output else "(empty)",
                    "```",
                    "",
                    "Failures: %s" % ", ".join(result.failures),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check model outputs against prompt contracts")
    parser.add_argument("--cases", required=True, help="JSONL file with case definitions")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--outputs", help="JSONL file with id/output records")
    source.add_argument("--command", help="model command; prompt on stdin, answer on stdout")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--report", help="write a Markdown report to this path")
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.cases)
        if args.outputs:
            outputs = load_outputs(args.outputs)
        else:
            outputs = {}
            for case in cases:
                outputs[case.id] = run_command(args.command, case.prompt, args.timeout)
        results = evaluate(cases, outputs)
    except DataError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    passed = sum(1 for result in results if result.passed)
    print("%d/%d passed" % (passed, len(results)))
    for result in results:
        if not result.passed:
            print("FAIL %s: %s" % (result.case_id, "; ".join(result.failures)))
    if args.report:
        report = render_report(results)
        try:
            Path(args.report).write_text(report, encoding="utf-8")
        except OSError as exc:
            print("error: cannot write report: %s" % exc, file=sys.stderr)
            return 2
        print("wrote %s" % args.report)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
