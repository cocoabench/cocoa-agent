"""
Test function for linear-regime-estimation-2-3.

Evaluates the JSON output for regime count and breakpoint dates.
"""

import json
import re
from datetime import datetime

# Ground truth values
EXPECTED_REGIME_COUNT = 3
EXPECTED_BREAKPOINTS = ["2024-09-01", "2024-09-24"]
TOLERANCE_DAYS = 7


def _parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD")


def _dates_within_tolerance(date1: datetime, date2: datetime, tolerance_days: int) -> bool:
    """Check if two dates are within tolerance."""
    delta = abs((date1 - date2).days)
    return delta <= tolerance_days


def _extract_json_from_text(text: str) -> dict | None:
    """Extract JSON object from text, handling code blocks and whitespace."""
    json_block_pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    match = json_block_pattern.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    json_pattern = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
    matches = json_pattern.findall(text)
    for maybe_json in matches:
        try:
            return json.loads(maybe_json)
        except json.JSONDecodeError:
            continue

    return None


def _extract_json_from_conversation(conversation: list) -> dict | None:
    """Extract JSON object from conversation history."""
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            for tc in message.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function", {})
                if func.get("name") == "task_complete":
                    try:
                        args_str = func.get("arguments", "{}")
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        if "result" in args:
                            result_str = args["result"]
                            json_obj = _extract_json_from_text(result_str)
                            if json_obj:
                                return json_obj
                    except (json.JSONDecodeError, Exception):
                        pass

    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or ""
        json_obj = _extract_json_from_text(content)
        if json_obj:
            return json_obj
    return None


def test(result: dict) -> dict:
    """
    Test executor result.

    Args:
        result: Result dict from TaskExecutor.run_task()

    Returns:
        Test dict with metrics and pass/fail status
    """
    conversation = result.get("conversation") or []
    task_completed = result.get("status") == "success"

    task_result = result.get("task_result")
    output_json = None
    if task_result:
        output_json = _extract_json_from_text(task_result)

    if not output_json:
        output_json = _extract_json_from_conversation(conversation)

    if not output_json:
        return {
            "passed": False,
            "feedback": "No valid JSON object found in assistant responses.",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    if "regime_count" not in output_json:
        return {
            "passed": False,
            "feedback": "JSON output missing 'regime_count' field.",
            "details": {
                "task_completed": task_completed,
                "output_json": output_json,
            },
        }

    if "breakpoints" not in output_json:
        return {
            "passed": False,
            "feedback": "JSON output missing 'breakpoints' field.",
            "details": {
                "task_completed": task_completed,
                "output_json": output_json,
            },
        }

    regime_count = output_json.get("regime_count")
    breakpoints = output_json.get("breakpoints", [])

    if not isinstance(regime_count, int):
        return {
            "passed": False,
            "feedback": f"regime_count must be an integer, got {type(regime_count).__name__}.",
            "details": {
                "task_completed": task_completed,
                "output_json": output_json,
            },
        }

    if not isinstance(breakpoints, list):
        return {
            "passed": False,
            "feedback": f"breakpoints must be a list, got {type(breakpoints).__name__}.",
            "details": {
                "task_completed": task_completed,
                "output_json": output_json,
            },
        }

    regime_count_correct = regime_count == EXPECTED_REGIME_COUNT

    if len(breakpoints) != len(EXPECTED_BREAKPOINTS):
        breakpoints_correct = False
        breakpoint_feedback = f"Expected {len(EXPECTED_BREAKPOINTS)} breakpoints, got {len(breakpoints)}."
    else:
        try:
            expected_dates = [_parse_date(bp) for bp in EXPECTED_BREAKPOINTS]
            output_dates = [_parse_date(bp) for bp in breakpoints]
            expected_dates.sort()
            output_dates.sort()

            all_within_tolerance = all(
                _dates_within_tolerance(exp_date, out_date, TOLERANCE_DAYS)
                for exp_date, out_date in zip(expected_dates, output_dates)
            )
            breakpoints_correct = all_within_tolerance

            if breakpoints_correct:
                breakpoint_feedback = "All breakpoints are within +/-7 day tolerance."
            else:
                mismatches = []
                for exp_date, out_date in zip(expected_dates, output_dates):
                    delta = abs((exp_date - out_date).days)
                    if delta > TOLERANCE_DAYS:
                        mismatches.append(
                            f"Expected {exp_date.strftime('%Y-%m-%d')}, got {out_date.strftime('%Y-%m-%d')} (delta: {delta} days)"
                        )
                breakpoint_feedback = "Breakpoint mismatches:\n" + "\n".join(mismatches)
        except ValueError as exc:
            breakpoints_correct = False
            breakpoint_feedback = f"Error parsing breakpoint dates: {str(exc)}"

    passed = task_completed and regime_count_correct and breakpoints_correct

    feedback_parts = []
    feedback_parts.append(f"Found JSON output: {json.dumps(output_json, indent=2)}")
    feedback_parts.append(
        f"{'OK' if regime_count_correct else 'WRONG'} Regime count: got {regime_count}, expected {EXPECTED_REGIME_COUNT}."
    )
    feedback_parts.append(breakpoint_feedback)
    if not task_completed:
        feedback_parts.append("Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "output_json": output_json,
            "regime_count_correct": regime_count_correct,
            "breakpoints_correct": breakpoints_correct,
            "expected_regime_count": EXPECTED_REGIME_COUNT,
            "expected_breakpoints": EXPECTED_BREAKPOINTS,
            "tolerance_days": TOLERANCE_DAYS,
        },
    }
