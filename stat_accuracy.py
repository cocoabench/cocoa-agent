#!/usr/bin/env python3
"""Summarize pass rate statistics from CocoaAgent result JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate accuracy/pass-rate statistics from result JSON files."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="results",
        help="Result directory (or a single JSON file). Defaults to ./results",
    )
    parser.add_argument(
        "--pattern",
        default="*.json",
        help="Glob pattern for JSON files when scanning directories (default: *.json)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top level of the directory",
    )
    parser.add_argument(
        "--show-passed",
        action="store_true",
        help="Print passed task names",
    )
    parser.add_argument(
        "--show-failed",
        action="store_true",
        help="Print evaluated-but-failed task names",
    )
    parser.add_argument(
        "--show-errors",
        action="store_true",
        help="Print errored task names and unreadable files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print summary as JSON",
    )
    return parser.parse_args()


def iter_result_files(path: Path, pattern: str, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    return sorted(path.rglob(pattern) if recursive else path.glob(pattern))


def classify_result(data: dict[str, Any]) -> str:
    status = data.get("status")
    eval_result = data.get("eval")

    if status == "error":
        return "error"

    if isinstance(eval_result, dict) and "passed" in eval_result:
        return "passed" if eval_result.get("passed") is True else "failed"

    if status == "success":
        return "unevaluated"

    return "unknown"


def print_name_block(title: str, names: list[str]) -> None:
    if not names:
        return
    print(f"\n{title}:")
    for name in names:
        print(f"  - {name}")


def main() -> None:
    args = parse_args()
    path = Path(args.path).resolve()
    recursive = not args.no_recursive
    files = iter_result_files(path, args.pattern, recursive)

    total_files = 0
    passed = 0
    failed = 0
    errors = 0
    unevaluated = 0
    unknown = 0
    unreadable = 0

    passed_names: list[str] = []
    failed_names: list[str] = []
    error_names: list[str] = []
    unreadable_names: list[str] = []

    for json_file in files:
        total_files += 1
        try:
            data = json.loads(json_file.read_text())
        except Exception as exc:
            unreadable += 1
            unreadable_names.append(f"{json_file}: {exc}")
            continue

        task_name = str(data.get("task_name") or json_file.stem)
        category = classify_result(data)

        if category == "passed":
            passed += 1
            passed_names.append(task_name)
        elif category == "failed":
            failed += 1
            failed_names.append(task_name)
        elif category == "error":
            errors += 1
            error_names.append(task_name)
        elif category == "unevaluated":
            unevaluated += 1
        else:
            unknown += 1

    evaluated = passed + failed
    overall_pass_rate = (passed / total_files * 100.0) if total_files else 0.0
    evaluated_accuracy = (passed / evaluated * 100.0) if evaluated else 0.0

    summary = {
        "path": str(path),
        "recursive": recursive,
        "files_scanned": total_files,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "unevaluated_success": unevaluated,
        "unknown": unknown,
        "unreadable": unreadable,
        "evaluated": evaluated,
        "overall_pass_rate_pct": round(overall_pass_rate, 2),
        "evaluated_accuracy_pct": round(evaluated_accuracy, 2),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
        return

    print(f"Scanning: {path}")
    print(f"Recursive: {recursive}")
    print("-" * 40)
    print(f"Files scanned:        {total_files}")
    print(f"Passed:               {passed}")
    print(f"Failed (evaluated):   {failed}")
    print(f"Errors:               {errors}")
    print(f"Unevaluated success:  {unevaluated}")
    print(f"Unknown format:       {unknown}")
    print(f"Unreadable JSON:      {unreadable}")
    print("-" * 40)
    print(f"Overall pass rate:    {overall_pass_rate:.2f}%")
    print(f"Accuracy on eval'd:   {evaluated_accuracy:.2f}%")

    if args.show_passed:
        print_name_block("Passed tasks", sorted(passed_names))
    if args.show_failed:
        print_name_block("Failed tasks", sorted(failed_names))
    if args.show_errors:
        print_name_block("Errored tasks", sorted(error_names))
        print_name_block("Unreadable files", unreadable_names)


if __name__ == "__main__":
    main()
