#!/usr/bin/env python3
"""Run one plaintext CocoaBench task through OpenClaw agent runtime."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def maybe_reexec_with_newer_python() -> None:
    if sys.version_info >= (3, 10):
        return
    for candidate in ("python3.13", "python3.12", "python3.11", "python3.10"):
        resolved = shutil.which(candidate)
        if resolved:
            os.execv(resolved, [resolved, __file__, *sys.argv[1:]])
    raise RuntimeError("Python 3.10+ is required to load CocoaBench test.py files, and no newer python3.x executable was found in PATH.")


maybe_reexec_with_newer_python()


DEFAULT_SESSION_INDEX = Path.home() / ".openclaw/agents/main/sessions/sessions.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", default=os.environ.get("OPENCLAW_MODEL", "gpt-5.4"))
    parser.add_argument("--thinking-mode", default=os.environ.get("OPENCLAW_THINKING_MODE", "high"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("OPENCLAW_TIMEOUT_SECONDS", "1800")))
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("OPENCLAW_MAX_STEPS", "50")))
    parser.add_argument("--session-id")
    parser.add_argument("--openclaw-bin", default=os.environ.get("OPENCLAW_BIN", "openclaw"))
    parser.add_argument("--session-index", default=str(DEFAULT_SESSION_INDEX))
    parser.add_argument("--skip-test", action="store_true")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify_task_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return cleaned[:24] or "task"


def default_session_id(task_name: str) -> str:
    return f"ocb-{slugify_task_name(task_name)}-{uuid.uuid4().hex[:12]}"


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


def run_command(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, env=env, check=False)


def parse_json_from_text(text: str) -> Any | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    best = None
    for start, ch in enumerate(raw):
        if ch not in "[{":
            continue
        try:
            value, end = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            continue
        if raw[start + end :].strip():
            best = value
            continue
        return value
    return best


def ensure_success(result: subprocess.CompletedProcess[str], command_name: str) -> None:
    if result.returncode == 0:
        return
    raise RuntimeError(
        f"{command_name} failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout.strip()}\n\n"
        f"stderr:\n{result.stderr.strip()}"
    )


def load_sessions_index(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected sessions index format in {path}")
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def load_model_status(openclaw_bin: str) -> dict[str, Any]:
    result = run_command([openclaw_bin, "models", "status", "--json"], env=os.environ.copy())
    ensure_success(result, "openclaw models status")
    payload = parse_json_from_text(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("Could not parse JSON from openclaw models status --json")
    return payload


def resolve_model_name(requested_model: str, model_status: dict[str, Any]) -> str:
    if "/" in requested_model:
        return requested_model

    aliases = model_status.get("aliases") or {}
    if isinstance(aliases, dict):
        alias_value = aliases.get(requested_model)
        if isinstance(alias_value, str) and alias_value.strip():
            return alias_value.strip()

    allowed = [item for item in (model_status.get("allowed") or []) if isinstance(item, str)]
    suffix_matches = [item for item in allowed if item.rsplit("/", 1)[-1] == requested_model]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    if len(suffix_matches) > 1:
        lowered = requested_model.lower()
        preferred_provider = None
        if lowered.startswith("gpt"):
            preferred_provider = "openai/"
        elif lowered.startswith("claude"):
            preferred_provider = "anthropic/"
        elif lowered.startswith("gemini"):
            preferred_provider = "google/"
        if preferred_provider is not None:
            for item in suffix_matches:
                if item.startswith(preferred_provider):
                    return item
        return suffix_matches[0]

    lowered = requested_model.lower()
    if lowered.startswith("gpt"):
        return f"openai/{requested_model}"
    if lowered.startswith("claude"):
        return f"anthropic/{requested_model}"
    if lowered.startswith("gemini"):
        return f"google/{requested_model}"
    return requested_model


def find_session_entry(entries: dict[str, dict[str, Any]], session_id: str) -> tuple[str, dict[str, Any]]:
    matches = []
    for key, entry in entries.items():
        if entry.get("sessionId") == session_id:
            matches.append((key, entry))
    if not matches:
        raise FileNotFoundError(f"No session entry found for session_id={session_id}")
    matches.sort(key=lambda item: item[1].get("updatedAt", 0), reverse=True)
    return matches[0]


def guess_session_file(session_index_path: Path, session_id: str, agent_stdout: str, agent_stderr: str) -> Path | None:
    combined = f"{agent_stdout}\n{agent_stderr}"

    match = re.search(r"sessionFile=([^\s]+\.jsonl)", combined)
    if match:
        candidate = Path(match.group(1)).expanduser()
        if candidate.exists():
            return candidate

    sessions_dir = session_index_path.expanduser().parent
    direct_candidate = sessions_dir / f"{session_id}.jsonl"
    if direct_candidate.exists():
        return direct_candidate

    return None


def resolve_session_artifacts(session_index_path: Path, session_id: str, agent_stdout: str, agent_stderr: str) -> tuple[str | None, Path]:
    entries = load_sessions_index(session_index_path)
    try:
        session_key, session_entry = find_session_entry(entries, session_id)
        session_file = Path(str(session_entry["sessionFile"])).expanduser()
        if session_file.exists():
            return session_key, session_file
    except FileNotFoundError:
        pass

    guessed = guess_session_file(session_index_path, session_id, agent_stdout, agent_stderr)
    if guessed is not None:
        return None, guessed

    raise FileNotFoundError(f"Could not resolve session file for session_id={session_id}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        entries.append(json.loads(stripped))
    return entries


def stringify_tool_args(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def normalize_tool_call(item: dict[str, Any]) -> dict[str, Any]:
    arguments = (
        item.get("arguments")
        or item.get("args")
        or item.get("input")
        or item.get("params")
        or {}
    )
    return {
        "id": item.get("toolCallId") or item.get("id"),
        "type": "function",
        "function": {
            "name": item.get("toolName") or item.get("name") or "unknown_tool",
            "arguments": stringify_tool_args(arguments),
        },
    }


def extract_text_from_content(content: Any, include_thinking: bool = False) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            if item.strip():
                parts.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "thinking":
            if include_thinking and isinstance(item.get("thinking"), str):
                parts.append(item["thinking"].strip())
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
            continue
        for key in ("outputText", "output_text", "input_text", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
                break
    return "\n\n".join(parts).strip()


def build_conversation(session_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conversation: list[dict[str, Any]] = []
    for entry in session_entries:
        if entry.get("type") != "message":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")

        if role in {"user", "assistant"}:
            normalized: dict[str, Any] = {
                "role": role,
                "content": extract_text_from_content(content),
            }
            if role == "assistant" and isinstance(content, list):
                tool_calls = [
                    normalize_tool_call(item)
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "toolCall"
                ]
                if tool_calls:
                    normalized["tool_calls"] = tool_calls
            conversation.append(normalized)
            continue

        if role == "toolResult":
            tool_name = message.get("toolName") or "tool"
            tool_text = extract_text_from_content(content)
            normalized_tool = {
                "role": "tool",
                "name": tool_name,
                "content": tool_text,
            }
            tool_call_id = message.get("toolCallId")
            if tool_call_id:
                normalized_tool["tool_call_id"] = tool_call_id
            conversation.append(normalized_tool)
    return conversation


def derive_task_result(conversation: list[dict[str, Any]]) -> str:
    for message in reversed(conversation):
        if message.get("role") != "assistant":
            continue
        for tool_call in reversed(message.get("tool_calls") or []):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            if function.get("name") != "task_complete":
                continue
            arguments = function.get("arguments")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and isinstance(parsed.get("result"), str):
                return parsed["result"]
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def count_tool_calls(conversation: list[dict[str, Any]]) -> int:
    total = 0
    for message in conversation:
        if message.get("role") == "assistant":
            tool_calls = message.get("tool_calls") or []
            if isinstance(tool_calls, list):
                total += len(tool_calls)
    return total


def extract_model_snapshot(session_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(session_entries):
        if entry.get("type") == "custom" and entry.get("customType") == "model-snapshot":
            data = entry.get("data")
            if isinstance(data, dict):
                return data
    return None


def extract_usage(agent_result: Any) -> dict[str, Any] | None:
    if isinstance(agent_result, dict):
        usage = agent_result.get("usage")
        if isinstance(usage, dict):
            return usage
        result = agent_result.get("result")
        if isinstance(result, dict) and isinstance(result.get("usage"), dict):
            return result["usage"]
    return None


def extract_cost(agent_result: Any) -> dict[str, Any] | None:
    if isinstance(agent_result, dict):
        cost = agent_result.get("cost")
        if isinstance(cost, dict):
            return cost
        result = agent_result.get("result")
        if isinstance(result, dict) and isinstance(result.get("cost"), dict):
            return result["cost"]
    return None


def run_test(test_path: Path, result: dict[str, Any]) -> dict[str, Any]:
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
    task_dir = Path(args.task_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    task_yaml = task_dir / "task.yaml"
    test_path = task_dir / "test.py"
    if not task_yaml.exists():
        raise FileNotFoundError(f"task.yaml not found in {task_dir}")

    instruction = load_instruction(task_yaml)
    session_id = args.session_id or default_session_id(task_dir.name)
    session_index_path = Path(args.session_index).expanduser()

    model_status = load_model_status(args.openclaw_bin)
    resolved_model = resolve_model_name(args.model, model_status)

    model_set_result = run_command([args.openclaw_bin, "models", "set", resolved_model], env=os.environ.copy())
    ensure_success(model_set_result, "openclaw models set")

    command = [
        args.openclaw_bin,
        "agent",
        "--local",
        "--json",
        "--session-id",
        session_id,
        "--thinking",
        args.thinking_mode,
        "--timeout",
        str(args.timeout_seconds),
        "--message",
        instruction,
    ]

    started_at = utc_now_iso()
    started_perf = time.perf_counter()
    agent_result_proc = run_command(command, env=os.environ.copy())
    execution_time = time.perf_counter() - started_perf
    finished_at = utc_now_iso()

    ensure_success(agent_result_proc, "openclaw agent")

    agent_result = parse_json_from_text(agent_result_proc.stdout)
    if agent_result is not None:
        (output_dir / "agent-response.json").write_text(json.dumps(agent_result, indent=2), encoding="utf-8")

    session_key, session_file = resolve_session_artifacts(
        session_index_path,
        session_id,
        agent_result_proc.stdout,
        agent_result_proc.stderr,
    )

    session_copy_path = output_dir / "session-trace.jsonl"
    shutil.copy2(session_file, session_copy_path)

    session_entries = read_jsonl(session_copy_path)
    conversation = build_conversation(session_entries)
    task_result = derive_task_result(conversation)
    tool_call_count = count_tool_calls(conversation)
    model_snapshot = extract_model_snapshot(session_entries)
    usage = extract_usage(agent_result)
    cost = extract_cost(agent_result)

    result: dict[str, Any] = {
        "task_name": task_dir.name,
        "task_dir": str(task_dir),
        "instruction": instruction,
        "status": "success",
        "task_result": task_result,
        "answer": task_result,
        "execution_time": execution_time,
        "started_at": started_at,
        "finished_at": finished_at,
        "tool_call_count": tool_call_count,
        "session_id": session_id,
        "session_key": session_key,
        "conversation": conversation,
        "request_config": {
            "requested_model": args.model,
            "resolved_model": resolved_model,
            "thinking_mode": args.thinking_mode,
            "local": True,
            "openclaw_bin": args.openclaw_bin,
        },
        "session_limits": {
            "max_steps": args.max_steps,
            "timeout_seconds": args.timeout_seconds,
        },
        "metadata": {
            "session_index_file": str(session_index_path),
            "session_file": str(session_file),
            "session_file_resolved_via_index": session_key is not None,
            "model_status": model_status,
            "model_snapshot": model_snapshot,
            "usage": usage,
            "cost": cost,
            "artifacts": {
                "session_trace": str(session_copy_path),
                "agent_response": None if agent_result is None else str(output_dir / "agent-response.json"),
            },
        },
    }
    if agent_result is not None:
        result["raw_agent_result"] = agent_result

    eval_result = None
    if not args.skip_test and test_path.exists():
        eval_result = run_test(test_path, result)
        result["eval"] = eval_result

    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if eval_result is not None:
        (output_dir / "eval.json").write_text(json.dumps(eval_result, indent=2), encoding="utf-8")

    summary = {
        "task": task_dir.name,
        "requested_model": args.model,
        "resolved_model": resolved_model,
        "thinking_mode": args.thinking_mode,
        "session_id": session_id,
        "passed": None if eval_result is None else eval_result.get("passed"),
        "feedback": None if eval_result is None else eval_result.get("feedback"),
        "execution_time": execution_time,
        "tool_call_count": tool_call_count,
        "timeout_seconds": args.timeout_seconds,
        "max_steps": args.max_steps,
        "result_path": str(result_path),
        "eval_path": None if eval_result is None else str(output_dir / "eval.json"),
        "session_trace_path": str(session_copy_path),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
