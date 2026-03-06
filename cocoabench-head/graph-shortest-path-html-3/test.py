"""
Test function for graph-shortest-path-html-3.
"""

import json
import re

EXPECTED_PATH = "v1->v4->v5->v8"
EXPECTED_WEIGHT = 9


def _extract_answer_block(text: str) -> str | None:
    match = re.search(r"<answer>(.*?)</answer>", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_path_weight(block: str) -> tuple[str | None, int | None]:
    path_match = re.search(r"PATH:\s*(.+?)(?:\n|TOTAL_WEIGHT|$)", block, flags=re.IGNORECASE | re.DOTALL)
    weight_match = re.search(r"TOTAL_WEIGHT:\s*(\d+)", block, flags=re.IGNORECASE)
    path = path_match.group(1).strip() if path_match else None
    weight = int(weight_match.group(1)) if weight_match else None
    return path, weight


def _normalize_path(path: str) -> str:
    normalized = re.sub(r"\s*[-=]+\s*>?\s*", "->", path)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.lower()


def _extract_from_conversation(conversation: list) -> str | None:
    for message in reversed(conversation or []):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            for tc in message.get("tool_calls", []):
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                if func.get("name") == "task_complete":
                    try:
                        args = func.get("arguments", "{}")
                        args_obj = json.loads(args) if isinstance(args, str) else args
                        result_text = args_obj.get("result", "")
                        block = _extract_answer_block(result_text)
                        if block:
                            return block
                    except Exception:
                        pass
        if message.get("role") == "assistant":
            block = _extract_answer_block(message.get("content") or "")
            if block:
                return block
    return None


def test(result: dict) -> dict:
    conversation = result.get("conversation") or []
    task_completed = result.get("status") == "success"

    output_block = None
    if result.get("task_result"):
        output_block = _extract_answer_block(result["task_result"])
    if not output_block:
        output_block = _extract_from_conversation(conversation)
    if not output_block:
        return {
            "passed": False,
            "feedback": "No valid <answer>...</answer> block found.",
            "details": {"task_completed": task_completed},
        }

    output_path, output_weight = _extract_path_weight(output_block)
    path_correct = bool(output_path) and _normalize_path(output_path) == _normalize_path(EXPECTED_PATH)
    weight_correct = output_weight == EXPECTED_WEIGHT
    passed = task_completed and path_correct and weight_correct

    return {
        "passed": passed,
        "feedback": (
            f"Found PATH={output_path}, TOTAL_WEIGHT={output_weight}\n"
            f"{'OK' if path_correct else 'WRONG'} expected path {EXPECTED_PATH}\n"
            f"{'OK' if weight_correct else 'WRONG'} expected weight {EXPECTED_WEIGHT}"
        ),
        "details": {
            "task_completed": task_completed,
            "output_path": output_path,
            "output_weight": output_weight,
            "expected_path": EXPECTED_PATH,
            "expected_weight": EXPECTED_WEIGHT,
        },
    }
