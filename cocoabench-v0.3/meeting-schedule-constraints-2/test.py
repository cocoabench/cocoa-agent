"""
Test function for meeting-schedule-constraints-2.

Evaluates the schedule format and correctness against the ground truth.
"""

import json
import re

# TimeSlot is like Mon-09:00, so we need a pattern that handles the hyphen inside it.
# Format: S1: Mon-09:00-RoomB-[Frank,Carol]
SESSION_PATTERN = re.compile(
    r'^S([1-4]):\s*(\w+-\d{2}:\d{2})-(Room\w+)-\[([^\]]+)\]$'
)

EXPECTED_ANSWER = {
    "S1": ("Mon-10:00", "RoomB", ["Frank", "Carol"]),
    "S2": ("Mon-11:00", "RoomB", ["Grace", "Judy"]),
    "S3": ("Mon-15:00", "RoomB", ["Frank", "Grace"]),
    "S4": ("Mon-09:00", "RoomB", ["Frank", "Carol", "Grace", "Judy"]),
}


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


def _parse_schedule(lines: list[str]) -> tuple[dict | None, str]:
    """Parse schedule lines into a structured dict. Returns (parsed, error_msg)."""
    if len(lines) != 4:
        return None, f"Expected 4 lines, got {len(lines)}"

    sessions = {}
    for line in lines:
        match = SESSION_PATTERN.match(line)
        if not match:
            return None, f"Invalid format: {line}"

        session_num = int(match.group(1))
        if session_num in sessions:
            return None, f"Duplicate session: S{session_num}"

        sessions[session_num] = {
            "time_slot": match.group(2).strip(),
            "room": match.group(3).strip(),
            "participants": sorted([p.strip() for p in match.group(4).split(',')]),
        }

    for i in range(1, 5):
        if i not in sessions:
            return None, f"Missing session: S{i}"

    return sessions, "Format valid"


def _check_correctness(parsed: dict) -> tuple[bool, list[str]]:
    """Check parsed schedule against ground truth."""
    errors = []
    for i in range(1, 5):
        key = f"S{i}"
        exp_slot, exp_room, exp_people = EXPECTED_ANSWER[key]
        got = parsed[i]
        if got["time_slot"] != exp_slot:
            errors.append(f"{key}: expected slot {exp_slot}, got {got['time_slot']}")
        if got["room"] != exp_room:
            errors.append(f"{key}: expected room {exp_room}, got {got['room']}")
        if got["participants"] != sorted(exp_people):
            errors.append(f"{key}: expected participants {sorted(exp_people)}, got {got['participants']}")
    return len(errors) == 0, errors


def test(result: dict) -> dict:
    """Test executor result."""
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
            "feedback": "No valid answer found in assistant responses. Expected format: <answer>S1: ...\nS2: ...\nS3: ...\nS4: ...</answer>",
            "details": {
                "task_completed": task_completed,
                "conversation_length": len(conversation),
            },
        }

    ans_lines = [line.strip() for line in output_answer.split('\n') if line.strip()]

    parsed, parse_msg = _parse_schedule(ans_lines)
    if parsed is None:
        return {
            "passed": False,
            "feedback": f"Format error: {parse_msg}",
            "details": {
                "task_completed": task_completed,
                "ans_lines": ans_lines,
                "format_valid": False,
                "format_feedback": parse_msg,
            },
        }

    correct, errors = _check_correctness(parsed)
    passed = task_completed and correct

    feedback_parts = []
    feedback_parts.append(f"Found answer with {len(ans_lines)} lines:")
    for line in ans_lines:
        feedback_parts.append(f"  {line}")
    feedback_parts.append(f"\n{'✓' if correct else '✗'} Correctness: {'all correct' if correct else '; '.join(errors)}")
    if not task_completed:
        feedback_parts.append("✗ Task status is not success.")

    return {
        "passed": passed,
        "feedback": "\n".join(feedback_parts),
        "details": {
            "task_completed": task_completed,
            "ans_lines": ans_lines,
            "format_valid": True,
            "answer_correct": correct,
            "errors": errors,
        },
    }
