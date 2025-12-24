"""
Test function for academic-citation-analysis.

Evaluates the citation analysis results for two Theory of Mind papers.
"""

import json
import re

# Ground truth values
EXPECTED_ANSWER = {
    "common_author": "Zhining Zhang",
    "autotom_cites_repbelief": "no",
    "common_references_count": 7,
    "autotom_refs_2023_plus": 26
}

# Tolerances for numeric fields
COMMON_REFS_TOLERANCE = 2  # Allow +/- 2 due to different counting methods
REFS_2023_PLUS_TOLERANCE = 3  # Allow +/- 3 for year counting variations


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
                            answer = _extract_answer_from_text(result_str)
                            if answer:
                                return answer
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
        return None


def _normalize_name(name: str | None) -> str:
    """Normalize author name for comparison."""
    if name is None:
        return ""
    # Convert to lowercase and remove extra whitespace
    return " ".join(name.lower().split())


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

    # First, check if task_result is directly provided in result dict
    task_result = result.get("task_result")
    output_answer = None
    if task_result:
        output_answer = _extract_answer_from_text(task_result)

    # If not found in task_result, extract from conversation
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
                "output_answer": output_answer,
            },
        }

    # Check each field
    checks = {}

    # Check common_author (case-insensitive, flexible name matching)
    got_author = _normalize_name(str(parsed_answer.get("common_author", "")))
    expected_author = _normalize_name(EXPECTED_ANSWER["common_author"])
    # Accept "zhining zhang" or just "zhang" as valid
    checks["common_author"] = (
        expected_author in got_author or
        got_author == expected_author or
        "zhining" in got_author and "zhang" in got_author
    )

    # Check autotom_cites_repbelief (yes/no)
    got_cites = str(parsed_answer.get("autotom_cites_repbelief", "")).lower().strip()
    expected_cites = EXPECTED_ANSWER["autotom_cites_repbelief"].lower()
    checks["autotom_cites_repbelief"] = got_cites == expected_cites

    # Check common_references_count (with tolerance)
    got_common_refs = parsed_answer.get("common_references_count")
    if isinstance(got_common_refs, (int, float)):
        diff = abs(int(got_common_refs) - EXPECTED_ANSWER["common_references_count"])
        checks["common_references_count"] = diff <= COMMON_REFS_TOLERANCE
    else:
        checks["common_references_count"] = False

    # Check autotom_refs_2023_plus (with tolerance)
    got_refs_2023 = parsed_answer.get("autotom_refs_2023_plus")
    if isinstance(got_refs_2023, (int, float)):
        diff = abs(int(got_refs_2023) - EXPECTED_ANSWER["autotom_refs_2023_plus"])
        checks["autotom_refs_2023_plus"] = diff <= REFS_2023_PLUS_TOLERANCE
    else:
        checks["autotom_refs_2023_plus"] = False

    all_correct = all(checks.values())
    passed = task_completed and all_correct

    feedback_parts = []

    # Common author feedback
    got_author_display = parsed_answer.get("common_author", "N/A")
    feedback_parts.append(
        f"{'✓' if checks['common_author'] else '✗'} Common author: got '{got_author_display}', expected '{EXPECTED_ANSWER['common_author']}'"
    )

    # Citation relationship feedback
    feedback_parts.append(
        f"{'✓' if checks['autotom_cites_repbelief'] else '✗'} AutoToM cites RepBelief: got '{got_cites}', expected '{expected_cites}'"
    )

    # Common references feedback
    got_common_refs_display = parsed_answer.get("common_references_count", "N/A")
    feedback_parts.append(
        f"{'✓' if checks['common_references_count'] else '✗'} Common references: got {got_common_refs_display}, expected {EXPECTED_ANSWER['common_references_count']} (tolerance: +/-{COMMON_REFS_TOLERANCE})"
    )

    # 2023+ refs feedback
    got_refs_2023_display = parsed_answer.get("autotom_refs_2023_plus", "N/A")
    feedback_parts.append(
        f"{'✓' if checks['autotom_refs_2023_plus'] else '✗'} AutoToM 2023+ refs: got {got_refs_2023_display}, expected {EXPECTED_ANSWER['autotom_refs_2023_plus']} (tolerance: +/-{REFS_2023_PLUS_TOLERANCE})"
    )

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
