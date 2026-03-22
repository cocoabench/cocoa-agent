#!/usr/bin/env python3
"""Run one plaintext CocoaBench task directly against an OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def load_instruction(task_yaml: Path) -> str:
    try:
      import yaml  # type: ignore
    except Exception:
      yaml = None

    if yaml is not None:
        data = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("instruction"), str):
            return data["instruction"]

    lines = task_yaml.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("instruction: |-") or line.startswith("instruction: |"):
            block = []
            for inner in lines[index + 1 :]:
                if inner.startswith("  "):
                    block.append(inner[2:])
                elif inner.strip() == "":
                    block.append("")
                else:
                    break
            return "\n".join(block).strip()
    raise ValueError(f"Could not extract instruction from {task_yaml}")


def call_openclaw(instruction: str) -> dict:
    base_url = os.environ["OPENCLAW_BASE_URL"].rstrip("/")
    api_key = os.environ["OPENCLAW_API_KEY"]
    model = os.environ["OPENCLAW_MODEL"]
    max_tokens = int(os.environ.get("MAX_TOKENS", "4000"))
    temperature = float(os.environ.get("TEMPERATURE", "0"))

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": instruction}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenClaw HTTP {exc.code}: {body}") from exc


def extract_content(response_json: dict) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        raise ValueError("No choices returned from OpenClaw")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    raise ValueError("Assistant response content missing or not a string")


def run_test(test_path: Path, result: dict) -> dict:
    spec = importlib.util.spec_from_file_location("task_test", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load test module from {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "test"):
        raise RuntimeError(f"{test_path} does not define test(result)")
    return module.test(result)


def main() -> int:
    args = parse_args()
    task_dir = Path(args.task_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task_yaml = task_dir / "task.yaml"
    test_path = task_dir / "test.py"
    instruction = load_instruction(task_yaml)

    response_json = call_openclaw(instruction)
    assistant_content = extract_content(response_json)

    result = {
        "task_name": task_dir.name,
        "task_dir": str(task_dir),
        "instruction": instruction,
        "status": "success",
        "task_result": assistant_content,
        "answer": assistant_content,
        "conversation": [
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": assistant_content},
        ],
        "metadata": {
            "model": os.environ["OPENCLAW_MODEL"],
            "base_url": os.environ["OPENCLAW_BASE_URL"],
            "response_id": response_json.get("id"),
            "object": response_json.get("object"),
        },
        "raw_response": response_json,
    }

    eval_result = None
    if os.environ.get("RUN_TEST", "true").lower() == "true" and test_path.exists():
        eval_result = run_test(test_path, result)
        result["eval"] = eval_result

    (output_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if eval_result is not None:
        (output_dir / "eval.json").write_text(json.dumps(eval_result, indent=2), encoding="utf-8")

    summary = {
        "task": task_dir.name,
        "passed": None if eval_result is None else eval_result.get("passed"),
        "result_path": str(output_dir / "result.json"),
        "eval_path": None if eval_result is None else str(output_dir / "eval.json"),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
