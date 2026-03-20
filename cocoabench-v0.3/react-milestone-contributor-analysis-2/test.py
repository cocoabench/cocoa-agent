"""
Test function for react-milestone-contributor-analysis-2.
"""

import json
import re


# Ground truth value from evaluation.md
EXPECTED_ANSWER = '''{ "top_contributor": "sophiebits", "top_contributor_issues": 10, "most_discussed_issue": 3220, "label_count": 5 }'''

# Answer type: "dict", "list", or "string"
# "dict"  - agent's answer must be valid JSON object matching the expected dict
# "list"  - agent's answer must be valid JSON array matching the expected list
# "string"- agent's answer is compared as plain text
ANSWER_TYPE = "dict"


def _strip_markdown_code_block(text: str) -> str:
    """
    Strip markdown code block markers from text.
    
    Handles formats like:
    - ```json\nEllipsis\n```
    - ```\nEllipsis\n```
    - Just the raw content
    """
    text = text.strip()
    
    # Pattern to match ```lang\n...\n``` or ```\n...\n```
    import re
    pattern = r'^```(?:\w+)?\s*\n(.*)\n```$'
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Also try without newlines (single line)
    pattern2 = r'^```(?:\w+)?\s*(.*)```$'
    match2 = re.match(pattern2, text, re.DOTALL)
    if match2:
        return match2.group(1).strip()
    
    return text


def _try_parse_json(text: str) -> dict | list | None:
    """Try to parse text as JSON, return None if failed."""
    text = _strip_markdown_code_block(text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _compare_answers(output: str, expected: str, answer_type: str) -> tuple[bool, str]:
    """
    Compare output answer with expected answer.

    Args:
        output: The agent's answer
        expected: The expected answer
        answer_type: "dict", "list", or "string"

    Returns:
        Tuple of (is_correct, error_message)
    """
    output = output.strip()
    expected = expected.strip()

    if answer_type == "dict":
        expected_parsed = _try_parse_json(expected)
        output_parsed = _try_parse_json(output)

        if not isinstance(expected_parsed, dict):
            return False, "Internal error: expected answer is not a valid JSON object"
        if not isinstance(output_parsed, dict):
            return False, f"Agent's answer is not a valid JSON object: {output[:100]}"
        if output_parsed == expected_parsed:
            return True, ""
        return False, "Dict mismatch"

    if answer_type == "list":
        expected_parsed = _try_parse_json(expected)
        output_parsed = _try_parse_json(output)

        if not isinstance(expected_parsed, list):
            return False, "Internal error: expected answer is not a valid JSON array"
        if not isinstance(output_parsed, list):
            return False, f"Agent's answer is not a valid JSON array: {output[:100]}"
        if output_parsed == expected_parsed:
            return True, ""
        return False, f"List mismatch (expected {len(expected_parsed)} items, got {len(output_parsed)})"

    # String comparison
    if output == expected:
        return True, ""
    return False, "String mismatch"


def _extract_answer_from_text(text: str) -> str | None:
    """Extract answer from <answer>...</answer> tags."""
    answer_pattern = re.compile(r'<answer>(.*?)</answer>', re.IGNORECASE | re.DOTALL)
    match = answer_pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_answer_from_conversation(conversation: list) -> str | None:
    """Extract answer from conversation history."""
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
    output_answer = None
    if task_result:
        output_answer = _extract_answer_from_text(task_result)
    
    if not output_answer:
        output_answer = _extract_answer_from_conversation(conversation)
    
    if not output_answer:
        return {
            "passed": False,
            "feedback": "No valid answer found. Expected format: <answer>YOUR_ANSWER</answer>",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    # Compare answers (supports both string and dict comparison)
    answer_correct, error_msg = _compare_answers(output_answer, EXPECTED_ANSWER, ANSWER_TYPE)

    passed = task_completed and answer_correct

    feedback_parts = []
    feedback_parts.append(f"Found answer: {output_answer}")
    if answer_correct:
        feedback_parts.append(f"✓ Answer correct (type: {ANSWER_TYPE})")
    else:
        feedback_parts.append(f"✗ Answer incorrect: {error_msg}")
        feedback_parts.append(f"  Expected: {EXPECTED_ANSWER}")
    if not task_completed:
        feedback_parts.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "output_answer": output_answer,
            "answer_correct": answer_correct,
            "expected_answer": EXPECTED_ANSWER,
            "answer_type": ANSWER_TYPE,
        },
    }
