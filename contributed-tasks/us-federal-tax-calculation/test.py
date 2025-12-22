"""
Test function for us-federal-tax-calculation.

Evaluates the federal income tax calculation result.
"""

import json
import re

# Ground truth value - Federal income tax (Regular Taxes) from PriorTax 2024 calculator
EXPECTED_ANSWER = 19693
TOLERANCE = 50  # Allow small tolerance for rounding differences


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


def _parse_dollar_amount(answer: str) -> int | None:
    """Parse dollar amount from answer string."""
    try:
        # Remove whitespace, dollar signs, commas
        cleaned = answer.strip().replace('$', '').replace(',', '')
        # Handle potential decimal values by rounding
        return round(float(cleaned))
    except ValueError:
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
            "feedback": "No valid answer found in assistant responses. Expected format: <answer>$19693</answer>",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    # Parse dollar amount from answer
    output_num = _parse_dollar_amount(output_answer)

    if output_num is None:
        return {
            "passed": False,
            "feedback": f"Could not parse answer as dollar amount: {output_answer}",
            "details": {
                "task_completed": task_completed,
                "output_answer": output_answer,
            },
        }

    # Check if answer matches (with tolerance)
    difference = abs(output_num - EXPECTED_ANSWER)
    answer_correct = difference <= TOLERANCE

    passed = task_completed and answer_correct

    feedback_parts = []
    feedback_parts.append(f"Found answer: {output_answer}")
    feedback_parts.append(
        f"{'✓' if answer_correct else '✗'} Federal tax: got ${output_num}, expected ${EXPECTED_ANSWER} (tolerance: ±${TOLERANCE})."
    )
    if difference > 0 and answer_correct:
        feedback_parts.append(f"  Difference: ${difference} (within tolerance)")
    elif difference > TOLERANCE:
        feedback_parts.append(f"  Difference: ${difference} (exceeds tolerance)")
    if not task_completed:
        feedback_parts.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "output_answer": output_answer,
            "output_number": output_num,
            "answer_correct": answer_correct,
            "expected_answer": EXPECTED_ANSWER,
            "difference": difference,
            "tolerance": TOLERANCE,
        },
    }
