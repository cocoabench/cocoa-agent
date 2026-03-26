"""
Smoke test for grounding on the 8-puzzle page.

The agent should identify the visible "Check Code" button, click it,
and then return a fixed completion token.
"""

import json
import re

EXPECTED_ANSWER = "CLICKED"
TARGET_BUTTON_TEXT = "CHECK CODE"
CLICK_ACTION_TYPES = {"browser_click", "dom_click"}


def _extract_answer_from_text(text: str) -> str | None:
    """Extract answer from <answer>...</answer> tags."""
    # Try to find answer in <answer> tags
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
            # Check if any tool call is task_complete with result
            for tc in message.get("tool_calls", []):
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function", {})
                if func.get("name") == "task_complete":
                    # Extract result from tool call arguments
                    try:
                        args_str = func.get("arguments", "{}")
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        if "result" in args:
                            result_str = args["result"]
                            # Try to extract answer from result
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


def _normalize_answer(answer: str) -> str:
    """Normalize answer for comparison (strip whitespace, uppercase)."""
    return answer.strip().upper()


def _trace_contains_click(execution_trace: list) -> bool:
    """Return True if the execution trace contains any click action."""
    for step in execution_trace or []:
        if not isinstance(step, dict):
            continue
        action = step.get("action") or {}
        if isinstance(action, dict) and action.get("action_type") in CLICK_ACTION_TYPES:
            return True
    return False


def _mentions_target_button(execution_trace: list, conversation: list) -> bool:
    """Return True if the target button text appears in trace feedback or conversation."""
    target = TARGET_BUTTON_TEXT.lower()

    for step in execution_trace or []:
        if not isinstance(step, dict):
            continue
        feedback = step.get("feedback") or {}
        if not isinstance(feedback, dict):
            continue
        for field in ("message", "observation"):
            value = feedback.get(field)
            if isinstance(value, str) and target in value.lower():
                return True

    for message in conversation or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and target in content.lower():
            return True

    return False


def test(result: dict) -> dict:
    """
    Test executor result.

    Args:
        result: Result dict from TaskExecutor.run_task()

    Returns:
        Test dict with metrics and pass/fail status
    """
    conversation = result.get("conversation") or []
    execution_trace = result.get("execution_trace") or []
    task_completed = result.get("status") == "success"

    # First, check if task_result is directly provided in result dict
    task_result = result.get("task_result")
    output_answer = None
    if task_result:
        # Try to extract answer from task_result
        output_answer = _extract_answer_from_text(task_result)
    
    # If not found in task_result, extract from conversation
    if not output_answer:
        output_answer = _extract_answer_from_conversation(conversation)
    
    if not output_answer:
        return {
            "passed": False,
            "feedback": "No valid answer found in assistant responses. Expected format: <answer>CODE</answer>",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    # Normalize answers for comparison (case-insensitive)
    normalized_output = _normalize_answer(output_answer)
    normalized_expected = _normalize_answer(EXPECTED_ANSWER)

    # Check if answer matches
    answer_correct = normalized_output == normalized_expected
    click_performed = _trace_contains_click(execution_trace)
    target_button_seen = _mentions_target_button(execution_trace, conversation)

    passed = task_completed and answer_correct and click_performed and target_button_seen

    feedback_parts = []
    feedback_parts.append(f"Found answer: {output_answer}")
    feedback_parts.append(
        f"{'✓' if answer_correct else '✗'} Final answer: got '{output_answer}', expected '{EXPECTED_ANSWER}'."
    )
    feedback_parts.append(
        f"{'✓' if click_performed else '✗'} Execution trace contains a click action."
    )
    feedback_parts.append(
        f"{'✓' if target_button_seen else '✗'} Run artifacts mention the target button text '{TARGET_BUTTON_TEXT}'."
    )
    if not task_completed:
        feedback_parts.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "output_answer": output_answer,
            "answer_correct": answer_correct,
            "click_performed": click_performed,
            "target_button_seen": target_button_seen,
            "expected_answer": EXPECTED_ANSWER,
        },
    }

