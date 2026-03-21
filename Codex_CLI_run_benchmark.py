#!/usr/bin/env python3
"""
Codex_CLI_run_benchmark.py — Batch Benchmark Runner for OpenAI Codex CLI

Automates running OpenAI Codex CLI (`codex exec`) against CocoaBench tasks.

Key mechanism:
  - `codex exec` runs Codex non-interactively (no TUI, no user prompts)
  - `--dangerously-bypass-approvals-and-sandbox` (--yolo) ensures ZERO
    interruptions — no approval dialogs, no sandbox permission prompts
  - `--output-last-message` captures the final assistant text to a file
  - `--json` streams JSONL events for progress monitoring
  - `--skip-git-repo-check` allows running in non-git temp directories
  - `--ephemeral` avoids persisting session state to disk

Workflow per task:
  1. Copy task folder to an isolated temp workspace, EXCLUDING solution.md,
     test.py, evaluation.md, __pycache__ (prevents answer leakage)
  2. Optionally create an AGENTS.md in the workspace for persistent guidance
  3. Invoke `codex exec` with the task prompt via stdin
  4. Capture the final message and JSONL conversation events
  5. Evaluate using task's test.py (primary) or solution.md (fallback)
  6. Log results to JSON

Codex JSONL event format (codex exec --json):
  - thread.started     — session begins, has thread_id
  - turn.started       — a new agent turn begins
  - item.started       — an item begins (command_execution shows command)
  - item.completed     — an item finishes with full content:
      - type=agent_message       — assistant text in "text" field
      - type=command_execution   — bash cmd in "command", output in
                                   "aggregated_output", "exit_code"
  - turn.completed     — turn finishes, has "usage" with token counts

Usage:
    python Codex_CLI_run_benchmark.py [OPTIONS]

Requirements:
    - Python 3.10+
    - Codex CLI installed (`npm i -g @openai/codex`) and authenticated

Examples:
    # Quick test with 2 tasks
    python Codex_CLI_run_benchmark.py --limit 2 --verbose

    # Full run with specific model
    python Codex_CLI_run_benchmark.py --model gpt-5.4

    # Run specific tasks in parallel
    python Codex_CLI_run_benchmark.py --tasks arrow-hunt nonogram-2 --workers 4

    # Resume after interruption
    python Codex_CLI_run_benchmark.py --skip-existing

    # Dump raw JSONL events for debugging event parsing
    python Codex_CLI_run_benchmark.py --tasks some-task --verbose --dump-events

Repository layout expected:
    cocoa-agent/
    ├── Codex_CLI_run_benchmark.py    <- this script
    ├── cocoabench-head/
    │   ├── some-task/
    │   │   ├── task.yaml
    │   │   ├── test.py              <- evaluation script (primary)
    │   │   ├── solution.md          <- expected answer (fallback)
    │   │   └── ...
    │   └── ...
    └── benchmark_results_codex/     <- auto-created output
"""

import subprocess
import json
import os
import re
import sys
import tempfile
import shutil
import time
import argparse
import threading
import importlib
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


# =============================================================================
# Configuration Constants
# =============================================================================

DEFAULT_BENCH_DIR = "cocoabench-head"
DEFAULT_OUTPUT_DIR = "benchmark_results_codex"
DEFAULT_TIMEOUT_SEC = 900            # 15 minutes per task
DEFAULT_WORKERS = 1                  # sequential by default
SOLUTION_FILENAME = "solution.md"
TASK_FILENAME = "task.yaml"

# Files/dirs excluded from agent workspace to prevent answer leakage.
WORKSPACE_EXCLUDE = [SOLUTION_FILENAME, "test.py", "evaluation.md", "__pycache__"]

# Approximate pricing for codex-mini-latest (USD per 1M tokens).
# Adjust these if using a different model.
COST_PER_M_INPUT = 1.50              # non-cached input tokens
COST_PER_M_CACHED_INPUT = 0.375      # cached input tokens
COST_PER_M_OUTPUT = 6.00             # output tokens

# AGENTS.md content placed in each workspace to guide Codex behavior.
AGENTS_MD_CONTENT = """\
# Benchmark Task Instructions

## Rules
- Read task.yaml for the full task description.
- Solve the task step by step. You may write and execute code as needed.
- When you have your final answer, output it using EXACTLY this XML format:
  <answer>YOUR_ANSWER_HERE</answer>
- Do NOT search for, read, or attempt to access any file named
  `solution.md`, `test.py`, or `evaluation.md`. They do not exist in
  your workspace.

## Workflow
1. Read task.yaml
2. Examine any other files in the working directory (data, images, code, etc.)
3. Reason through the problem; run code if helpful
4. Output your final answer inside <answer> tags
"""


# =============================================================================
# Task Discovery
# =============================================================================

def find_tasks(bench_dir: Path) -> list[Path]:
    """
    Scan the benchmark directory and return a sorted list of task folders.
    A valid task folder must contain task.yaml.
    """
    if not bench_dir.exists():
        print(f"  ERROR: Benchmark directory '{bench_dir}' not found.")
        print(f"  Make sure you run this script from the repo root.")
        sys.exit(1)

    tasks = []
    for entry in sorted(bench_dir.iterdir()):
        if entry.is_dir() and (entry / TASK_FILENAME).exists():
            tasks.append(entry)
    return tasks


# =============================================================================
# test.py Evaluation (PRIMARY METHOD)
# =============================================================================

def evaluate_with_test_py(
    task_dir: Path,
    raw_result: str,
    status: str,
    conversation: list,
    instruction: str,
    num_turns: int,
) -> Optional[dict]:
    """
    Load the task's test.py and call its test(result) function.

    Returns dict with {passed, feedback, details} or None if test.py
    is unavailable.
    """
    test_py_path = task_dir / "test.py"
    if not test_py_path.exists():
        return None

    module_name = f"task_test_{task_dir.name.replace('-', '_').replace('.', '_')}"
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, str(test_py_path))
    if spec is None or spec.loader is None:
        return {
            "passed": False,
            "feedback": f"Failed to create module spec for {test_py_path}",
            "details": {"error": "spec_creation_failed"},
        }

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        return {
            "passed": False,
            "feedback": f"Failed to load test.py: {exc}",
            "details": {"error": str(exc)},
        }

    test_func = getattr(module, "test", None)
    if test_func is None:
        return {
            "passed": False,
            "feedback": "test.py does not define a test() function",
            "details": {"error": "no_test_function"},
        }

    result_dict = {
        "task_name": task_dir.name,
        "task_result": raw_result,
        "conversation": conversation,
        "execution_trace": [],
        "status": status,
        "instruction": instruction,
        "iterations": num_turns or 0,
        "sandbox": {},
    }

    try:
        test_output = test_func(result_dict)
        if not isinstance(test_output, dict):
            return {
                "passed": False,
                "feedback": f"test() returned non-dict: {type(test_output)}",
                "details": {"error": "invalid_return_type"},
            }
        return test_output
    except Exception as exc:
        return {
            "passed": False,
            "feedback": f"test() raised an exception: {exc}",
            "details": {"error": str(exc)},
        }


# =============================================================================
# Expected Answer Extraction (FALLBACK — from solution.md)
# =============================================================================

def extract_expected_answer(task_dir: Path) -> Optional[str]:
    """
    Read solution.md and extract the expected answer.
    Used as fallback when test.py is not available.
    """
    sol_path = task_dir / SOLUTION_FILENAME
    if not sol_path.exists():
        return None

    text = sol_path.read_text(encoding="utf-8", errors="replace")

    # Priority 1: <answer>...</answer>
    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Priority 2: "ANSWER: value"
    m = re.search(r"^\s*ANSWER\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Priority 3a: **Expected Answer[...]:** value (same line)
    m = re.search(
        r"\*\*Expected\s+Answer[^*]*\*\*\s*:?\s*(.+)", text, re.IGNORECASE
    )
    if m:
        val = re.sub(r"^\*\*(.+)\*\*$", r"\1", m.group(1).strip())
        if val:
            return val

    # Priority 3b: **Expected Answer[...]:** with value on next line(s)
    m = re.search(
        r"\*\*Expected\s+Answer[^*]*\*\*\s*:?\s*\n\s*(.+?)(?:\n\s*\n|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if m:
        val = re.sub(r"^\*\*(.+)\*\*$", r"\1", m.group(1).strip())
        if val:
            return val

    # Priority 4: ### Final Answer heading
    m = re.search(
        r"#{1,6}\s*Final\s+Answer\b[^\n]*\n(.*?)(?=\n\s*#{1,6}\s|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if m and m.group(1).strip():
        return m.group(1).strip()

    # Priority 5: ## Answer heading
    m = re.search(
        r"#{1,6}\s*Answer\s*\n(.*?)(?=\n\s*#{1,6}\s|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if m and m.group(1).strip():
        return m.group(1).strip()

    # Priority 6: Bold label + bold value on next line
    bold_pairs = re.findall(r"\*\*[^*]+\*\*\s*\n\s*\*\*([^*]+)\*\*", text)
    if bold_pairs:
        return bold_pairs[-1].strip()

    # Priority 7: "Final Answer:" inline
    m = re.search(
        r"Final\s+Answer\s*[:\-]\s*(.+?)(?:\n\s*\n|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if m and m.group(1).strip():
        return m.group(1).strip()

    return None


# =============================================================================
# Workspace Isolation
# =============================================================================

def create_workspace(task_dir: Path, tmp_root: str, git_init: bool = False) -> Path:
    """
    Copy the task folder into a temp directory, EXCLUDING answer files.
    Optionally initialize a git repo for better Codex compatibility.
    Also creates an AGENTS.md to guide Codex behavior.
    """
    dest = Path(tmp_root) / task_dir.name
    shutil.copytree(
        task_dir, dest,
        ignore=shutil.ignore_patterns(*WORKSPACE_EXCLUDE),
    )

    # Create AGENTS.md for persistent agent guidance
    agents_path = dest / "AGENTS.md"
    agents_path.write_text(AGENTS_MD_CONTENT, encoding="utf-8")

    if git_init:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "benchmark",
            "GIT_AUTHOR_EMAIL": "bench@test.local",
            "GIT_COMMITTER_NAME": "benchmark",
            "GIT_COMMITTER_EMAIL": "bench@test.local",
        }
        subprocess.run(
            ["git", "init"], cwd=str(dest),
            capture_output=True, env=env, timeout=10,
        )
        subprocess.run(
            ["git", "add", "."], cwd=str(dest),
            capture_output=True, env=env, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", "init benchmark workspace"], cwd=str(dest),
            capture_output=True, env=env, timeout=10,
        )

    return dest


# =============================================================================
# Prompt Building
# =============================================================================

def build_prompt(task_yaml_content: str) -> str:
    """
    Construct the prompt sent to Codex via `codex exec`.
    """
    return (
        "You are solving a benchmark task. "
        "The current working directory contains the task files.\n\n"
        "Instructions:\n"
        "1. Read the task description below carefully.\n"
        "2. List and examine any other files in the current directory that may "
        "be relevant (data files, images, code, CSVs, etc.).\n"
        "3. Solve the task step by step. Write and run code if needed.\n"
        "4. When you have your final answer, you MUST output it using EXACTLY "
        "this format:\n"
        "   <answer>YOUR_ANSWER_HERE</answer>\n\n"
        "CRITICAL RULE: Do NOT search for, read, or access any file named "
        "'solution.md', 'test.py', or 'evaluation.md'. "
        "They do not exist in your workspace.\n\n"
        "--- TASK DESCRIPTION (from task.yaml) ---\n"
        f"{task_yaml_content}\n"
        "--- END TASK DESCRIPTION ---\n"
    )


# =============================================================================
# Answer Extraction
# =============================================================================

def extract_answer(text: str) -> Optional[str]:
    """
    Extract the answer from Codex's response text.
    Looks for <answer> tags first, falls back to last non-empty line.
    """
    if not text:
        return None

    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        return lines[-1]

    return None


# =============================================================================
# Answer Comparison (FALLBACK)
# =============================================================================

def normalize(s: str) -> str:
    s = s.strip().lower()
    s = s.rstrip(".,;:!?")
    s = re.sub(r"\s+", " ", s)
    return s


def compare_answers(
    agent_answer: Optional[str], expected: Optional[str]
) -> Optional[bool]:
    if agent_answer is None or expected is None:
        return None

    a, b = normalize(agent_answer), normalize(expected)
    if not a or not b:
        return None

    if a == b:
        return True

    try:
        if abs(float(a) - float(b)) < 1e-9:
            return True
    except (ValueError, OverflowError):
        pass

    if len(b) <= 60 and b in a:
        return True
    if len(a) <= 60 and a in b:
        return True

    return False


# =============================================================================
# Codex Event Helpers
# =============================================================================

_BASH_PREFIX = "/bin/bash -lc "


def _extract_inner_command(full_cmd: str) -> str:
    """
    Extract the user-facing command from Codex's /bin/bash -lc wrapper.

    Examples:
      '/bin/bash -lc pwd'                       → 'pwd'
      '/bin/bash -lc "sed -n \'1,200p\' f.txt"' → "sed -n '1,200p' f.txt"
      '/bin/bash -lc \'rg --files\''             → 'rg --files'
    """
    if not full_cmd.startswith(_BASH_PREFIX):
        return full_cmd
    inner = full_cmd[len(_BASH_PREFIX):]
    # Strip one layer of outer quotes if present
    if len(inner) >= 2:
        if (inner[0] == '"' and inner[-1] == '"') or \
           (inner[0] == "'" and inner[-1] == "'"):
            inner = inner[1:-1]
    return inner


def _estimate_cost(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> float:
    """
    Estimate USD cost from token counts using module-level pricing constants.
    """
    new_input = max(input_tokens - cached_input_tokens, 0)
    cost = (
        new_input * COST_PER_M_INPUT / 1_000_000
        + cached_input_tokens * COST_PER_M_CACHED_INPUT / 1_000_000
        + output_tokens * COST_PER_M_OUTPUT / 1_000_000
    )
    return cost


# =============================================================================
# Run a Single Task via `codex exec`
# =============================================================================

def run_single_task(
    task_dir: Path,
    workspace: Path,
    model: Optional[str] = None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    verbose: bool = False,
    dump_events: bool = False,
    git_init: bool = False,
) -> dict:
    """
    Invoke `codex exec` on a single task in the isolated workspace.

    Returns a dict with: answer, raw_result, conversation, elapsed,
    exit_code, num_turns, usage, estimated_cost, full_events, stderr, error
    """
    task_text = (workspace / TASK_FILENAME).read_text(
        encoding="utf-8", errors="replace"
    )
    prompt = build_prompt(task_text)

    output_file = workspace / "_codex_last_message.txt"

    # ── Build the codex exec command ──
    cmd = ["codex", "exec"]

    if model:
        cmd += ["--model", model]

    cmd += [
        "--json",
        "--output-last-message", str(output_file),
        "--dangerously-bypass-approvals-and-sandbox",
        "--cd", str(workspace),
        "--ephemeral",
        "--color", "never",
    ]

    # If workspace is not a git repo, skip the check
    if not git_init:
        cmd.append("--skip-git-repo-check")

    # Use "-" as prompt placeholder to read from stdin
    cmd.append("-")

    if verbose:
        safe_cmd = " ".join(
            c if not c.startswith("You are") else "'<prompt>'" for c in cmd
        )
        print(f"\n    [CMD] {safe_cmd}")
        print(f"    [CWD] {workspace}")

    t0 = time.time()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    conversation: list[dict] = []
    all_events: list[dict] = []
    last_result_text = ""
    num_turns = 0
    total_input_tokens = 0
    total_cached_input_tokens = 0
    total_output_tokens = 0
    proc = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # ── Write prompt to stdin and close ──
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except BrokenPipeError:
            pass  # Process may have exited early

        # ── Read stderr in background thread ──
        def read_stderr():
            try:
                for line in proc.stderr:
                    stderr_chunks.append(line)
            except Exception:
                pass

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        # ── Stream and parse JSONL events from stdout ──
        deadline = t0 + timeout_sec

        for line in proc.stdout:
            stdout_chunks.append(line)
            now = time.time()

            line_stripped = line.strip()
            if not line_stripped:
                continue

            try:
                event = json.loads(line_stripped)
            except json.JSONDecodeError:
                if verbose:
                    print(f"    [RAW] {line_stripped[:200]}")
                continue

            all_events.append(event)
            event_type = event.get("type", "")

            # ── Dump raw event JSON if requested ──
            if dump_events:
                compact = json.dumps(event, ensure_ascii=False)
                if len(compact) > 500:
                    compact = compact[:500] + "..."
                print(f"    [DUMP] {compact}")

            # ==============================================================
            # Parse Codex CLI JSONL events
            # ==============================================================

            # ── item.started: show tool calls as they begin ──
            if event_type == "item.started":
                item = event.get("item", {})
                if isinstance(item, dict):
                    itype = item.get("type", "")
                    if itype == "command_execution":
                        raw_cmd = item.get("command", "")
                        inner_cmd = _extract_inner_command(raw_cmd)
                        if verbose and not dump_events:
                            display = inner_cmd[:120]
                            if len(inner_cmd) > 120:
                                display += "..."
                            print(
                                f"    [TOOL]   Bash: "
                                f"{{'command': '{display}'}}"
                            )

            # ── item.completed: record content ──
            elif event_type == "item.completed":
                item = event.get("item", {})
                if not isinstance(item, dict):
                    continue

                itype = item.get("type", "")

                # ── Agent message (assistant text) ──
                if itype == "agent_message":
                    text = item.get("text", "")
                    if text:
                        last_result_text = text
                        conversation.append({
                            "role": "assistant",
                            "content": text,
                        })
                        if verbose and not dump_events:
                            preview = text.replace("\n", " ")[:300]
                            print(f"    [CODEX] {preview}")

                # ── Command execution (tool call + result) ──
                elif itype == "command_execution":
                    raw_cmd = item.get("command", "")
                    output = item.get("aggregated_output", "")
                    inner_cmd = _extract_inner_command(raw_cmd)

                    # Record the tool call
                    conversation.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": item.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": "Bash",
                                "arguments": json.dumps(
                                    {"command": inner_cmd},
                                    ensure_ascii=False,
                                ),
                            },
                        }],
                    })

                    # Record the tool output
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": item.get("id", ""),
                        "content": output,
                    })

                # ── Unknown item type ──
                else:
                    if verbose and not dump_events:
                        text = item.get("text", "")
                        if text:
                            preview = text.replace("\n", " ")[:200]
                            print(
                                f"    [{itype.upper() or 'ITEM'}] "
                                f"{preview}"
                            )

            # ── turn.completed: track usage ──
            elif event_type == "turn.completed":
                num_turns += 1
                usage = event.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_cached_input_tokens += usage.get(
                    "cached_input_tokens", 0
                )
                total_output_tokens += usage.get("output_tokens", 0)

                if verbose and not dump_events:
                    total_tok = total_input_tokens + total_output_tokens
                    cost = _estimate_cost(
                        total_input_tokens,
                        total_cached_input_tokens,
                        total_output_tokens,
                    )
                    print()
                    print(
                        f"    [DONE] tokens={total_tok} "
                        f"({total_input_tokens}in/"
                        f"{total_output_tokens}out), "
                        f"turns={num_turns}, "
                        f"est_cost=${cost:.4f}"
                    )

            # ── turn.started / thread.started: silent ──
            elif event_type in ("turn.started", "thread.started"):
                pass

            # ── Fallback for unknown event types ──
            elif verbose and not dump_events:
                print(f"    [EVENT] type={event_type}")

            # ── Check timeout ──
            if now > deadline:
                proc.kill()
                proc.wait()
                elapsed = time.time() - t0

                final_text = _read_output_file(output_file, last_result_text)
                answer = extract_answer(final_text)
                cost = _estimate_cost(
                    total_input_tokens,
                    total_cached_input_tokens,
                    total_output_tokens,
                )

                return {
                    "answer": answer,
                    "raw_result": final_text or "(timeout, partial captured)",
                    "conversation": conversation,
                    "elapsed": round(elapsed, 2),
                    "exit_code": -1,
                    "num_turns": num_turns,
                    "usage": {
                        "input_tokens": total_input_tokens,
                        "cached_input_tokens": total_cached_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": (
                            total_input_tokens + total_output_tokens
                        ),
                    },
                    "estimated_cost": round(cost, 6),
                    "full_events": all_events,
                    "stderr": "".join(stderr_chunks)[:2000],
                    "error": f"Timeout after {timeout_sec}s",
                }

        # ── Process finished normally ──
        proc.wait()
        stderr_thread.join(timeout=5)
        elapsed = time.time() - t0

        # ── Read the final message from output file (most reliable) ──
        final_text = _read_output_file(output_file, last_result_text)
        answer = extract_answer(final_text)
        cost = _estimate_cost(
            total_input_tokens,
            total_cached_input_tokens,
            total_output_tokens,
        )

        return {
            "answer": answer,
            "raw_result": final_text,
            "conversation": conversation,
            "elapsed": round(elapsed, 2),
            "exit_code": proc.returncode,
            "num_turns": num_turns,
            "usage": {
                "input_tokens": total_input_tokens,
                "cached_input_tokens": total_cached_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
            },
            "estimated_cost": round(cost, 6),
            "full_events": all_events,
            "stderr": "".join(stderr_chunks)[:2000],
            "error": None,
        }

    except FileNotFoundError:
        return _error_result(0, (
            "'codex' command not found. "
            "Install with: npm i -g @openai/codex"
        ))

    except Exception as exc:
        if proc is not None:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
        return _error_result(time.time() - t0, str(exc))


def _read_output_file(output_file: Path, fallback_text: str) -> str:
    """
    Read the --output-last-message file. Falls back to the text
    accumulated from JSONL streaming if the file doesn't exist.
    """
    try:
        if output_file.exists():
            content = output_file.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                return content.strip()
    except Exception:
        pass
    return fallback_text


def _error_result(elapsed: float, error_msg: str) -> dict:
    return {
        "answer": None,
        "raw_result": "",
        "conversation": [],
        "elapsed": round(elapsed, 2),
        "exit_code": -1,
        "num_turns": 0,
        "usage": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        "estimated_cost": 0.0,
        "full_events": [],
        "stderr": "",
        "error": error_msg,
    }


# =============================================================================
# Single-task wrapper (for parallel execution)
# =============================================================================

def run_and_evaluate_single(
    task_dir: Path,
    out_dir: Path,
    model: Optional[str],
    timeout_sec: int,
    verbose: bool,
    dump_events: bool,
    git_init: bool,
) -> dict:
    """
    Complete pipeline for one task: workspace → run → evaluate → save.
    Each call creates and cleans up its own temp directory.
    """
    name = task_dir.name

    with tempfile.TemporaryDirectory(prefix=f"codex_bench_{name}_") as tmp_root:
        # 1. Create isolated workspace
        workspace = create_workspace(task_dir, tmp_root, git_init=git_init)

        # 2. Run Codex
        result = run_single_task(
            task_dir=task_dir,
            workspace=workspace,
            model=model,
            timeout_sec=timeout_sec,
            verbose=verbose,
            dump_events=dump_events,
            git_init=git_init,
        )

    # 3. Evaluate — primary: test.py, fallback: solution.md
    has_error = bool(result.get("error"))
    exit_ok = result.get("exit_code", -1) == 0
    task_status = "success" if (not has_error and exit_ok) else "failed"

    task_text = (task_dir / TASK_FILENAME).read_text(
        encoding="utf-8", errors="replace"
    )

    test_py_output = evaluate_with_test_py(
        task_dir=task_dir,
        raw_result=result.get("raw_result", ""),
        status=task_status,
        conversation=result.get("conversation", []),
        instruction=task_text,
        num_turns=result.get("num_turns") or 0,
    )

    if test_py_output is not None:
        passed = test_py_output.get("passed", False)
        feedback = test_py_output.get("feedback", "")
        eval_details = test_py_output.get("details", {})
        eval_method = "test.py"
        agent_ans = eval_details.get("output_answer") or result.get("answer")
        expected_ans = eval_details.get("expected_answer")
    else:
        expected_ans = extract_expected_answer(task_dir)
        agent_ans = result.get("answer")
        match = compare_answers(agent_ans, expected_ans)
        passed = match
        feedback = ""
        eval_details = {}
        eval_method = "solution.md"

    # ── Normalize answers to str (test.py may return int/float) ──
    if agent_ans is not None and not isinstance(agent_ans, str):
        agent_ans = str(agent_ans)
    if expected_ans is not None and not isinstance(expected_ans, str):
        expected_ans = str(expected_ans)

    # 4. Build record
    record = {
        "task": name,
        "passed": passed,
        "eval_method": eval_method,
        "feedback": feedback,
        "agent_answer": agent_ans,
        "expected_answer": expected_ans,
        "elapsed_seconds": result.get("elapsed"),
        "num_turns": result.get("num_turns"),
        "exit_code": result.get("exit_code"),
        "error": result.get("error"),
        "usage": result.get("usage"),
        "estimated_cost": result.get("estimated_cost"),
        "eval_details": eval_details,
        "timestamp": datetime.now().isoformat(),
    }

    # 5. Save per-task detail file
    detail = {
        **record,
        "raw_result": (result.get("raw_result") or "")[:5000],
        "stderr": result.get("stderr", ""),
    }
    detail_path = out_dir / f"{name}.json"
    detail_path.write_text(
        json.dumps(detail, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return record


# =============================================================================
# Print Helpers
# =============================================================================

def status_icon(passed: Optional[bool]) -> str:
    if passed is True:
        return "✅"
    elif passed is False:
        return "❌"
    return "⚠️"


def truncate(s: Optional[str], length: int = 50) -> str:
    if s is None:
        return "(none)"
    if not isinstance(s, str):
        s = str(s)
    if not s:
        return "(none)"
    s = s.replace("\n", " ")
    return s[:length] + "..." if len(s) > length else s


def _format_cost(cost: Optional[float]) -> str:
    """Format cost for display, e.g. '$0.0291'."""
    if cost is None or cost == 0:
        return ""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.3f}"


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "CocoaBench Benchmark Runner — batch-run OpenAI Codex CLI "
            "on benchmark tasks"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python Codex_CLI_run_benchmark.py --limit 2 --verbose
  python Codex_CLI_run_benchmark.py --model gpt-5.4
  python Codex_CLI_run_benchmark.py --tasks task-a task-b --workers 4
  python Codex_CLI_run_benchmark.py --skip-existing
  python Codex_CLI_run_benchmark.py --dry-run
  python Codex_CLI_run_benchmark.py --tasks some-task --verbose --dump-events
""",
    )

    parser.add_argument(
        "--dir", default=DEFAULT_BENCH_DIR,
        help=f"Benchmark task directory (default: {DEFAULT_BENCH_DIR})",
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--model", default=None,
        help="Codex model (e.g. gpt-5.4, gpt-5.3-codex). Omit for default.",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SEC,
        help=f"Timeout in seconds per task (default: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument(
        "--tasks", nargs="+", default=None,
        help="Only run specific task folder names (space-separated)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only run the first N tasks",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS} = sequential)",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip tasks with existing result JSON in output dir",
    )
    parser.add_argument(
        "--git-init", action="store_true",
        help="Initialize a git repo in each workspace (better Codex compat)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List tasks and exit without running",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print tool calls, assistant messages, and turn info",
    )
    parser.add_argument(
        "--dump-events", action="store_true",
        help="Dump raw JSONL events (for debugging event parsing)",
    )

    args = parser.parse_args()

    bench_dir = Path(args.dir)
    out_dir = Path(args.out)

    # ── Banner ──
    print()
    print("=" * 62)
    print("   CocoaBench Runner for OpenAI Codex CLI")
    print("=" * 62)

    # ── Verify codex CLI ──
    try:
        ver_proc = subprocess.run(
            ["codex", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        cli_version = ver_proc.stdout.strip() or "(unknown)"
        print(f"   Codex CLI   : {cli_version}")
    except FileNotFoundError:
        print("   ERROR: 'codex' command not found!")
        print("   Install: npm i -g @openai/codex")
        print("   Then run: codex   (to authenticate)")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("   WARNING: 'codex --version' timed out. Continuing...")

    # ── Check authentication ──
    try:
        login_proc = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True, text=True, timeout=15,
        )
        if login_proc.returncode != 0:
            print("   WARNING: Codex may not be authenticated.")
            print("   Run 'codex login' or set OPENAI_API_KEY.")
    except Exception:
        pass

    # ── Discover tasks ──
    all_tasks = find_tasks(bench_dir)
    print(f"   Bench dir   : {bench_dir.resolve()}")
    print(f"   Tasks found : {len(all_tasks)}")
    print(f"   Output dir  : {out_dir.resolve()}")
    print(f"   Model       : {args.model or '(default)'}")
    print(f"   Timeout     : {args.timeout}s per task")
    print(f"   Workers     : {args.workers}")
    print(f"   Git init    : {'yes' if args.git_init else 'no'}")
    print(f"   Eval method : test.py (primary) + solution.md (fallback)")

    # ── Filter tasks ──
    tasks = all_tasks[:]

    if args.tasks:
        requested = set(args.tasks)
        tasks = [t for t in tasks if t.name in requested]
        missing = requested - {t.name for t in tasks}
        if missing:
            print(f"   WARNING: not found: {missing}")
        print(f"   Filtered    : {len(tasks)} tasks by name")

    if args.limit:
        tasks = tasks[: args.limit]
        print(f"   Limited     : first {args.limit}")

    if args.skip_existing:
        out_dir.mkdir(parents=True, exist_ok=True)
        before = len(tasks)
        tasks = [t for t in tasks if not (out_dir / f"{t.name}.json").exists()]
        skipped = before - len(tasks)
        if skipped:
            print(f"   Skipped     : {skipped} already completed")

    print(f"   To run      : {len(tasks)}")
    print("=" * 62)

    # ── Dry run ──
    if args.dry_run:
        print("\n   [DRY RUN] Task list:\n")
        for i, t in enumerate(tasks, 1):
            has_test = "✓" if (t / "test.py").exists() else "✗"
            has_sol = "✓" if (t / SOLUTION_FILENAME).exists() else "✗"
            print(
                f"   {i:4d}. {t.name:45s}  "
                f"test.py={has_test}  solution.md={has_sol}"
            )
        print(f"\n   Total: {len(tasks)} tasks.\n")
        return

    if not tasks:
        print("\n   Nothing to run. Done.\n")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Execute tasks ──
    print(f"\n   Starting {len(tasks)} tasks...\n")
    results: list[dict] = []

    if args.workers <= 1:
        # ── Sequential execution ──
        for idx, task_dir in enumerate(tasks, 1):
            name = task_dir.name
            print(
                f"   [{idx:3d}/{len(tasks)}] {name:40s} ",
                end="", flush=True,
            )

            record = run_and_evaluate_single(
                task_dir=task_dir,
                out_dir=out_dir,
                model=args.model,
                timeout_sec=args.timeout,
                verbose=args.verbose,
                dump_events=args.dump_events,
                git_init=args.git_init,
            )
            results.append(record)
            _print_record_line(record, args.verbose)
    else:
        # ── Parallel execution ──
        print(f"   Using {args.workers} parallel workers\n")
        future_to_task = {}

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for task_dir in tasks:
                fut = executor.submit(
                    run_and_evaluate_single,
                    task_dir=task_dir,
                    out_dir=out_dir,
                    model=args.model,
                    timeout_sec=args.timeout,
                    verbose=args.verbose,
                    dump_events=args.dump_events,
                    git_init=args.git_init,
                )
                future_to_task[fut] = task_dir

            completed = 0
            for fut in as_completed(future_to_task):
                completed += 1
                task_dir = future_to_task[fut]
                name = task_dir.name
                try:
                    record = fut.result()
                except Exception as exc:
                    record = {
                        "task": name,
                        "passed": None,
                        "eval_method": "none",
                        "feedback": "",
                        "agent_answer": None,
                        "expected_answer": None,
                        "elapsed_seconds": 0,
                        "num_turns": 0,
                        "exit_code": -1,
                        "error": str(exc),
                        "usage": None,
                        "estimated_cost": 0.0,
                        "eval_details": {},
                        "timestamp": datetime.now().isoformat(),
                    }

                results.append(record)
                print(
                    f"   [{completed:3d}/{len(tasks)}] {name:40s} ",
                    end="", flush=True,
                )
                _print_record_line(record, args.verbose)

    # ── Summary ──
    _print_summary(results, out_dir, args)


def _print_record_line(record: dict, verbose: bool):
    """Print a single-line status for a completed task."""
    icon = status_icon(record.get("passed"))
    elapsed = record.get("elapsed_seconds", 0)
    parts = [f"{elapsed:.0f}s"]

    cost = record.get("estimated_cost")
    cost_str = _format_cost(cost)
    if cost_str:
        parts.append(cost_str)

    if record.get("num_turns"):
        parts.append(f"{record['num_turns']}t")

    parts.append(f"[{record.get('eval_method', '?')}]")

    if record.get("error"):
        parts.append(f"ERR: {record['error'][:40]}")

    print(f"{icon}  {', '.join(parts)}")

    if verbose or record.get("passed") is False:
        print(
            f"            got:      "
            f"\"{truncate(record.get('agent_answer'))}\""
        )
        print(
            f"            expected: "
            f"\"{truncate(record.get('expected_answer'))}\""
        )
        if record.get("feedback"):
            for fb_line in record["feedback"].splitlines()[:5]:
                print(f"            {fb_line}")


def _print_summary(results: list[dict], out_dir: Path, args):
    """Print and save the overall summary."""
    total = len(results)
    n_passed = sum(1 for r in results if r["passed"] is True)
    n_failed = sum(1 for r in results if r["passed"] is False)
    n_unknown = sum(1 for r in results if r["passed"] is None)
    n_errors = sum(1 for r in results if r.get("error"))
    n_test_py = sum(1 for r in results if r["eval_method"] == "test.py")
    n_fallback = sum(1 for r in results if r["eval_method"] == "solution.md")
    evaluable = n_passed + n_failed
    accuracy = round(n_passed / max(evaluable, 1) * 100, 2)
    avg_time = round(
        sum(r.get("elapsed_seconds") or 0 for r in results) / max(total, 1), 1
    )

    # Aggregate token usage
    sum_input = 0
    sum_cached = 0
    sum_output = 0
    for r in results:
        u = r.get("usage")
        if isinstance(u, dict):
            sum_input += u.get("input_tokens", 0)
            sum_cached += u.get("cached_input_tokens", 0)
            sum_output += u.get("output_tokens", 0)
    sum_total_tokens = sum_input + sum_output
    total_cost = sum(r.get("estimated_cost") or 0 for r in results)

    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "model": args.model or "default",
        "benchmark_dir": str(args.dir),
        "total_tasks": total,
        "passed": n_passed,
        "failed": n_failed,
        "unknown_or_missing": n_unknown,
        "errors": n_errors,
        "evaluable": evaluable,
        "accuracy_pct": accuracy,
        "eval_by_test_py": n_test_py,
        "eval_by_solution_md": n_fallback,
        "avg_seconds_per_task": avg_time,
        "total_tokens": sum_total_tokens,
        "total_input_tokens": sum_input,
        "total_cached_input_tokens": sum_cached,
        "total_output_tokens": sum_output,
        "total_estimated_cost": round(total_cost, 6),
        "config": {
            "timeout_sec": args.timeout,
            "workers": args.workers,
            "git_init": args.git_init,
        },
        "per_task": results,
    }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    cost_str = _format_cost(total_cost) or "$0"

    print()
    print("=" * 62)
    print("   RESULTS SUMMARY")
    print("-" * 62)
    print(f"   Total tasks      : {total}")
    print(f"   ✅ Passed         : {n_passed}")
    print(f"   ❌ Failed         : {n_failed}")
    print(f"   ⚠️  Unknown/Skip   : {n_unknown}")
    print(f"   💥 Errors         : {n_errors}")
    print(f"   📈 Accuracy       : {accuracy}%  ({n_passed}/{evaluable})")
    print(
        f"   💰 Est. cost      : {cost_str}  "
        f"({sum_input}in/{sum_output}out tokens)"
    )
    print(f"   ⏱️  Avg time       : {avg_time}s / task")
    print(f"   🧪 Eval: test.py  : {n_test_py} tasks")
    print(f"   📄 Eval: fallback : {n_fallback} tasks")
    print(f"   📁 Full results   : {summary_path}")
    print("=" * 62)
    print()


if __name__ == "__main__":
    main()