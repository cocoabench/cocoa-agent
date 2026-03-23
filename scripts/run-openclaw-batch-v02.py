#!/usr/bin/env python3
"""Run CocoaBench v0.2 tasks in batch through the OpenClaw agent runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
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
    raise RuntimeError("Python 3.10+ is required, and no newer python3.x executable was found in PATH.")


maybe_reexec_with_newer_python()


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DEFAULT_TASKS_DIR = ROOT_DIR / "cocoabench-v0.2"
DEFAULT_OUTPUTS_DIR = ROOT_DIR / "outputs"
RUNNER_PATH = SCRIPT_DIR / "run-openclaw-agent-task.py"
DECRYPT_PATH = ROOT_DIR / "decrypt.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-dir", default=str(DEFAULT_TASKS_DIR))
    parser.add_argument("--output-dir")
    parser.add_argument("--model", default=os.environ.get("OPENCLAW_MODEL", "gpt-5.4"))
    parser.add_argument("--thinking-mode", default=os.environ.get("OPENCLAW_THINKING_MODE", "high"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("OPENCLAW_TIMEOUT_SECONDS", "1800")))
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("OPENCLAW_MAX_STEPS", "50")))
    parser.add_argument("--task", action="append", dest="tasks", help="Run only the named task. Repeatable.")
    parser.add_argument("--limit", type=int, help="Run at most N discovered tasks.")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--rerun-completed", action="store_true")
    parser.add_argument("--skip-test", action="store_true")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "run"


def default_output_dir(model: str, thinking_mode: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_slug = safe_slug(model.replace("/", "-"))
    return DEFAULT_OUTPUTS_DIR / f"openclaw-v02-{model_slug}-{thinking_mode}-{timestamp}"


def load_decrypt_module():
    spec = importlib.util.spec_from_file_location("decrypt_module", DECRYPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load decrypt helper from {DECRYPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_tasks(tasks_dir: Path) -> list[Path]:
    tasks = []
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue
        if (task_dir / "task.yaml.enc").exists() and (task_dir / "test.py.enc").exists() and (task_dir / "canary.txt").exists():
            tasks.append(task_dir)
    return tasks


def load_manifest(path: Path, *, model: str, thinking_mode: str, tasks_dir: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "dataset": "cocoabench-v0.2",
        "tasks_dir": str(tasks_dir),
        "requested_model": model,
        "thinking_mode": thinking_mode,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "tasks": {},
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    counter = Counter()
    passed = 0
    failed_eval = 0
    for task_name, record in (manifest.get("tasks") or {}).items():
        status = record.get("status", "unknown")
        counter[status] += 1
        if record.get("passed") is True:
            passed += 1
        elif status == "completed" and record.get("passed") is False:
            failed_eval += 1
    return {
        "dataset": manifest.get("dataset"),
        "requested_model": manifest.get("requested_model"),
        "thinking_mode": manifest.get("thinking_mode"),
        "updated_at": utc_now_iso(),
        "counts": dict(counter),
        "passed_tasks": passed,
        "completed_but_failed_eval": failed_eval,
        "total_tasks_seen": len(manifest.get("tasks") or {}),
    }


def should_run(task_name: str, record: dict[str, Any] | None, args: argparse.Namespace) -> bool:
    if record is None:
        return True
    status = record.get("status")
    if status == "completed":
        return args.rerun_completed
    if status == "failed":
        return args.rerun_failed
    if status == "running":
        return True
    return True


def decrypt_task_into_output(task_dir: Path, task_output_dir: Path, decrypt_module: Any) -> tuple[Path, Path]:
    canary = decrypt_module.read_canary(task_dir)
    if not canary:
        raise RuntimeError(f"Missing canary for task: {task_dir}")
    task_yaml = decrypt_module.decrypt_file_to_memory(task_dir / "task.yaml.enc", canary)
    test_py = decrypt_module.decrypt_file_to_memory(task_dir / "test.py.enc", canary)
    task_yaml_path = task_output_dir / "task.yaml"
    test_py_path = task_output_dir / "test.py"
    task_yaml_path.write_text(task_yaml, encoding="utf-8")
    test_py_path.write_text(test_py, encoding="utf-8")
    return task_yaml_path, test_py_path


def run_single_task(task_output_dir: Path, args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(RUNNER_PATH),
        "--task-dir",
        str(task_output_dir),
        "--output-dir",
        str(task_output_dir),
        "--model",
        args.model,
        "--thinking-mode",
        args.thinking_mode,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--max-steps",
        str(args.max_steps),
    ]
    if args.skip_test:
        command.append("--skip-test")
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> int:
    args = parse_args()
    tasks_dir = Path(args.tasks_dir).resolve()
    if not tasks_dir.exists():
        raise FileNotFoundError(f"Tasks directory not found: {tasks_dir}")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(args.model, args.thinking_mode)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "manifest.json"
    summary_path = output_dir / "summary.json"
    manifest = load_manifest(manifest_path, model=args.model, thinking_mode=args.thinking_mode, tasks_dir=tasks_dir)
    decrypt_module = load_decrypt_module()

    task_dirs = discover_tasks(tasks_dir)
    if args.tasks:
        requested = set(args.tasks)
        task_dirs = [task_dir for task_dir in task_dirs if task_dir.name in requested]
    if args.limit is not None:
        task_dirs = task_dirs[: args.limit]

    for task_dir in task_dirs:
        task_name = task_dir.name
        task_output_dir = output_dir / task_name
        task_output_dir.mkdir(parents=True, exist_ok=True)
        record = (manifest.get("tasks") or {}).get(task_name)
        if not should_run(task_name, record, args):
            continue

        manifest.setdefault("tasks", {})[task_name] = {
            "status": "running",
            "task_dir": str(task_dir),
            "output_dir": str(task_output_dir),
            "started_at": utc_now_iso(),
            "requested_model": args.model,
            "thinking_mode": args.thinking_mode,
        }
        manifest["updated_at"] = utc_now_iso()
        write_json(manifest_path, manifest)
        write_json(summary_path, build_summary(manifest))

        try:
            decrypt_task_into_output(task_dir, task_output_dir, decrypt_module)
            proc = run_single_task(task_output_dir, args)
            runner_summary_path = task_output_dir / "runner-summary.json"
            if proc.stdout.strip():
                summary_payload = json.loads(proc.stdout)
                write_json(runner_summary_path, summary_payload)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"runner exited with code {proc.returncode}")

            eval_path = task_output_dir / "eval.json"
            result_path = task_output_dir / "result.json"
            eval_payload = json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else None
            result_payload = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None

            manifest["tasks"][task_name] = {
                "status": "completed",
                "task_dir": str(task_dir),
                "output_dir": str(task_output_dir),
                "started_at": manifest["tasks"][task_name]["started_at"],
                "finished_at": utc_now_iso(),
                "requested_model": args.model,
                "thinking_mode": args.thinking_mode,
                "passed": None if eval_payload is None else eval_payload.get("passed"),
                "feedback": None if eval_payload is None else eval_payload.get("feedback"),
                "result_path": str(result_path),
                "eval_path": None if not eval_path.exists() else str(eval_path),
                "session_trace_path": str(task_output_dir / "session-trace.jsonl"),
                "tool_call_count": None if result_payload is None else result_payload.get("tool_call_count"),
                "execution_time": None if result_payload is None else result_payload.get("execution_time"),
            }
        except Exception as exc:
            manifest["tasks"][task_name] = {
                "status": "failed",
                "task_dir": str(task_dir),
                "output_dir": str(task_output_dir),
                "started_at": manifest["tasks"][task_name]["started_at"],
                "finished_at": utc_now_iso(),
                "requested_model": args.model,
                "thinking_mode": args.thinking_mode,
                "error": str(exc),
            }

        manifest["updated_at"] = utc_now_iso()
        write_json(manifest_path, manifest)
        write_json(summary_path, build_summary(manifest))

    print(json.dumps(build_summary(manifest), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
