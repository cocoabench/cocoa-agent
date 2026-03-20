"""Evaluator for model-release-form-2."""

import re

EXPECTED = "<answer>V2-RELEASE-APPROVED-E8CA0BA87B</answer>"
def _extract_candidate(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"<answer>\s*([^<\n]+)\s*</answer>", text)
    if not m:
        return None
    token = m.group(1).strip()
    return f"<answer>{token}</answer>"


def _extract_from_conversation(conversation: list) -> str | None:
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue

        if message.get("tool_calls"):
            for tc in message.get("tool_calls", []):
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                if func.get("name") == "task_complete":
                    args = func.get("arguments", "")
                    cand = _extract_candidate(args if isinstance(args, str) else str(args))
                    if cand:
                        return cand

        cand = _extract_candidate(message.get("content") or "")
        if cand:
            return cand
    return None


def test(result: dict) -> dict:
    task_result = result.get("task_result") or ""
    conversation = result.get("conversation") or []

    candidate = _extract_candidate(task_result) or _extract_from_conversation(conversation)

    if candidate is None:
        return {
            "passed": False,
            "feedback": "No <answer>...</answer> output found.",
            "details": {"expected": EXPECTED, "received": None},
        }

    if candidate != EXPECTED:
        return {
            "passed": False,
            "feedback": "Answer mismatch.",
            "details": {"expected": EXPECTED, "received": candidate},
        }

    return {
        "passed": True,
        "feedback": "Correct final approval token.",
        "details": {"expected": EXPECTED, "received": candidate},
    }
