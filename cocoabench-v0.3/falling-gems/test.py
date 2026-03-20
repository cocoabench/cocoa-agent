"""
Test function for falling-gems.
"""

import json
import re


EXPECTED_ANSWER = "32"


def _extract_answer_from_text(text: str) -> str | None:
    """Extract answer from text with a strict-first, permissive-fallback approach."""
    if not text:
        return None

    tag_match = re.search(r"<answer>(.*?)</answer>", text, flags=re.IGNORECASE | re.DOTALL)
    if tag_match:
        return tag_match.group(1).strip()

    stripped = text.strip()
    if re.fullmatch(r"\d+", stripped):
        return stripped

    nums = re.findall(r"\b\d+\b", stripped)
    if nums:
        return nums[-1]

    return None


def _extract_answer_from_conversation(conversation: list) -> str | None:
    """Extract answer from assistant tool call result first, then assistant content."""
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            for tc in message.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function", {})
                if func.get("name") != "task_complete":
                    continue
                try:
                    args_raw = func.get("arguments", "{}")
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    result_text = args.get("result", "")
                    answer = _extract_answer_from_text(result_text)
                    if answer:
                        return answer
                except Exception:
                    continue

    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        answer = _extract_answer_from_text(message.get("content") or "")
        if answer:
            return answer

    return None


def test(result: dict) -> dict:
    """Evaluate result with exact-match score check."""
    conversation = result.get("conversation") or []
    task_completed = result.get("status") == "success"

    output_answer = None
    task_result = result.get("task_result")
    if task_result:
        output_answer = _extract_answer_from_text(task_result)

    if not output_answer:
        output_answer = _extract_answer_from_conversation(conversation)

    if not output_answer:
        return {
            "passed": False,
            "feedback": "No valid answer found. Expected format: <answer>FINAL_BLUE_SCORE</answer>",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    answer_correct = output_answer == EXPECTED_ANSWER
    passed = task_completed and answer_correct

    feedback_lines = [
        f"Found answer: {output_answer}",
        (
            f"✓ Score correct."
            if answer_correct
            else f"✗ Score incorrect: expected {EXPECTED_ANSWER}, got {output_answer}."
        ),
    ]
    if not task_completed:
        feedback_lines.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_lines),
        "details": {
            "task_completed": task_completed,
            "output_answer": output_answer,
            "expected_answer": EXPECTED_ANSWER,
            "answer_correct": answer_correct,
        },
    }
