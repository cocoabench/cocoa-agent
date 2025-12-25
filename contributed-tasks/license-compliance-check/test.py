"""
Test function for license-compliance-check.

Evaluates the license analysis results for @angular/cli@17.0.0.
"""

import json
import re

# Ground truth values
EXPECTED_ANSWER = {
    "total_packages": 230,
    "license_types_count": 10,
    "blueoak_packages": ["jackspeak", "package-json-from-dist", "path-scurry"],
    "cc_by_package": "spdx-exceptions",
    "blueoak_type": "permissive",
    "mit_compatible": "yes",
    "attribution_license": "CC-BY-3.0"
}

# Tolerances
PACKAGE_COUNT_TOLERANCE = 15  # Allow ±15 due to dependency resolution variations
LICENSE_COUNT_TOLERANCE = 2   # Allow ±2 for license counting variations


def _extract_answer_from_text(text: str) -> str | None:
    """Extract answer from <answer>...</answer> tags."""
    answer_pattern = re.compile(r'<answer>(.*?)</answer>', re.IGNORECASE | re.DOTALL)
    match = answer_pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_answer_from_conversation(conversation: list) -> str | None:
    """Extract answer from conversation history."""
    # First, check assistant messages with tool_calls for task_complete with result parameter
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
                            # First try to extract from <answer> tags
                            answer = _extract_answer_from_text(result_str)
                            if answer:
                                return answer
                            # If no tags found, return the raw result (may be JSON directly)
                            if result_str and result_str.strip():
                                return result_str.strip()
                    except (json.JSONDecodeError, Exception):
                        pass

    # Search through assistant messages in reverse order for answer in content
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or ""
        answer = _extract_answer_from_text(content)
        if answer:
            return answer
    return None


def _parse_json_answer(answer: str) -> dict | None:
    """Parse JSON from answer string."""
    try:
        # Try to parse as JSON directly
        return json.loads(answer)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        json_pattern = re.compile(r'```(?:json)?\s*(.*?)\s*```', re.DOTALL)
        match = json_pattern.search(answer)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try to find JSON object pattern
        json_obj_pattern = re.compile(r'\{[^{}]*\}', re.DOTALL)
        match = json_obj_pattern.search(answer)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None


def _normalize_package_name(name: str) -> str:
    """Normalize package name by removing version and lowercasing."""
    # Remove version suffix if present (e.g., "pkg@1.0.0" -> "pkg")
    if "@" in name and not name.startswith("@"):
        name = name.split("@")[0]
    elif name.startswith("@") and name.count("@") > 1:
        # Scoped package like "@scope/pkg@1.0.0"
        parts = name.rsplit("@", 1)
        name = parts[0]
    return name.lower().strip()


def _check_package_list(got: list, expected: list) -> bool:
    """Check if package lists match (order-independent, case-insensitive)."""
    if not isinstance(got, list):
        return False
    got_normalized = set(_normalize_package_name(p) for p in got if isinstance(p, str))
    expected_normalized = set(_normalize_package_name(p) for p in expected)
    return got_normalized == expected_normalized


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

    # Extract answer from conversation
    output_answer = None
    task_result = result.get("task_result")
    if task_result:
        output_answer = _extract_answer_from_text(task_result)
        if not output_answer:
            output_answer = task_result

    if not output_answer:
        output_answer = _extract_answer_from_conversation(conversation)

    if not output_answer:
        return {
            "passed": False,
            "feedback": "No valid answer found. Expected format: <answer>{...}</answer>",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    # Parse JSON from answer
    parsed_answer = _parse_json_answer(output_answer)

    if parsed_answer is None:
        return {
            "passed": False,
            "feedback": f"Could not parse answer as JSON: {output_answer[:200]}",
            "details": {
                "task_completed": task_completed,
                "output_answer": output_answer[:500],
            },
        }

    # Check each field
    checks = {}
    feedback_parts = []

    # 1. Check total_packages (with tolerance)
    got_total = parsed_answer.get("total_packages")
    if isinstance(got_total, (int, float)):
        diff = abs(int(got_total) - EXPECTED_ANSWER["total_packages"])
        checks["total_packages"] = diff <= PACKAGE_COUNT_TOLERANCE
    else:
        checks["total_packages"] = False
    feedback_parts.append(
        f"{'✓' if checks['total_packages'] else '✗'} total_packages: got {got_total}, expected {EXPECTED_ANSWER['total_packages']} (±{PACKAGE_COUNT_TOLERANCE})"
    )

    # 2. Check license_types_count (with tolerance)
    got_license_count = parsed_answer.get("license_types_count")
    if isinstance(got_license_count, (int, float)):
        diff = abs(int(got_license_count) - EXPECTED_ANSWER["license_types_count"])
        checks["license_types_count"] = diff <= LICENSE_COUNT_TOLERANCE
    else:
        checks["license_types_count"] = False
    feedback_parts.append(
        f"{'✓' if checks['license_types_count'] else '✗'} license_types_count: got {got_license_count}, expected {EXPECTED_ANSWER['license_types_count']} (±{LICENSE_COUNT_TOLERANCE})"
    )

    # 3. Check blueoak_packages (list comparison)
    got_blueoak = parsed_answer.get("blueoak_packages", [])
    checks["blueoak_packages"] = _check_package_list(got_blueoak, EXPECTED_ANSWER["blueoak_packages"])
    feedback_parts.append(
        f"{'✓' if checks['blueoak_packages'] else '✗'} blueoak_packages: got {got_blueoak}, expected {EXPECTED_ANSWER['blueoak_packages']}"
    )

    # 4. Check cc_by_package (string comparison)
    got_cc_by = _normalize_package_name(str(parsed_answer.get("cc_by_package", "")))
    expected_cc_by = _normalize_package_name(EXPECTED_ANSWER["cc_by_package"])
    checks["cc_by_package"] = got_cc_by == expected_cc_by
    feedback_parts.append(
        f"{'✓' if checks['cc_by_package'] else '✗'} cc_by_package: got '{parsed_answer.get('cc_by_package')}', expected '{EXPECTED_ANSWER['cc_by_package']}'"
    )

    # 5. Check blueoak_type (permissive/copyleft)
    got_type = str(parsed_answer.get("blueoak_type", "")).lower().strip()
    checks["blueoak_type"] = got_type == EXPECTED_ANSWER["blueoak_type"]
    feedback_parts.append(
        f"{'✓' if checks['blueoak_type'] else '✗'} blueoak_type: got '{got_type}', expected '{EXPECTED_ANSWER['blueoak_type']}'"
    )

    # 6. Check mit_compatible (yes/no)
    got_mit = str(parsed_answer.get("mit_compatible", "")).lower().strip()
    checks["mit_compatible"] = got_mit == EXPECTED_ANSWER["mit_compatible"]
    feedback_parts.append(
        f"{'✓' if checks['mit_compatible'] else '✗'} mit_compatible: got '{got_mit}', expected '{EXPECTED_ANSWER['mit_compatible']}'"
    )

    # 7. Check attribution_license
    got_attr = str(parsed_answer.get("attribution_license", "")).upper().strip()
    expected_attr = EXPECTED_ANSWER["attribution_license"].upper()
    # Allow some flexibility in naming (CC-BY-3.0, CC BY 3.0, etc.)
    checks["attribution_license"] = "CC" in got_attr and ("BY" in got_attr or "ATTRIBUTION" in got_attr)
    feedback_parts.append(
        f"{'✓' if checks['attribution_license'] else '✗'} attribution_license: got '{parsed_answer.get('attribution_license')}', expected '{EXPECTED_ANSWER['attribution_license']}'"
    )

    all_correct = all(checks.values())
    passed = task_completed and all_correct

    if not task_completed:
        feedback_parts.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "parsed_answer": parsed_answer,
            "expected_answer": EXPECTED_ANSWER,
            "checks": checks,
            "all_correct": all_correct,
        },
    }
