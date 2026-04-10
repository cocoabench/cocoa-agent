#!/usr/bin/env python3
"""
Claude_Code_run_benchmark.py — Batch Benchmark Runner for Claude Code CLI

Automates running Claude Code (the `claude` CLI) against CocoaBench tasks.

Workflow per task:
  1. Copy task folder to a temp workspace, EXCLUDING solution.md, test.py, evaluation.md
  2. Invoke `claude -p` (non-interactive) with the task description
  3. Capture Claude's full response and conversation from stream-json events
  4. Evaluate using the task's test.py (primary) or solution.md comparison (fallback)
  5. Log results to JSON

Usage:
    python Claude_Code_run_benchmark.py [OPTIONS]

Requirements:
    - Python 3.10+
    - Claude Code CLI installed and authenticated

Repository layout expected:
    cocoa-agent/
    ├── Claude_Code_run_benchmark.py      <- this script
    ├── cocoabench-head/
    │   ├── some-task/
    │   │   ├── task.yaml
    │   │   ├── test.py           <- evaluation script (primary)
    │   │   ├── solution.md       <- expected answer (fallback)
    │   │   └── ...
    │   └── ...
    └── benchmark_results/                <- auto-created output
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


# =============================================================================
# Configuration Constants
# =============================================================================

DEFAULT_BENCH_DIR = "cocoabench-head"
DEFAULT_OUTPUT_DIR = "benchmark_results"
DEFAULT_MAX_TURNS = 100
DEFAULT_TIMEOUT_SEC = 900          # 15 minutes per task
SOLUTION_FILENAME = "solution.md"
TASK_FILENAME = "task.yaml"

# Files to exclude from the agent workspace to prevent answer leakage.
# test.py contains EXPECTED_ANSWER; solution.md / evaluation.md contain answers.
WORKSPACE_EXCLUDE = [SOLUTION_FILENAME, "test.py", "evaluation.md"]


# =============================================================================
# Task Discovery
# =============================================================================

def find_tasks(bench_dir: Path) -> list[Path]:
    """
    Scan the benchmark directory and return sorted list of task folders.
    A valid task folder must contain a file named task.yaml.
    """
    if not bench_dir.exists():
        print(f"  ERROR: Benchmark directory '{bench_dir}' not found.")
        print(f"  Make sure you run this script from the repo root (cocoa-agent/).")
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

    Args:
        task_dir:      Original task directory (contains test.py with EXPECTED_ANSWER)
        raw_result:    Claude's raw output text (should contain <answer>...</answer>)
        status:        "success" or "failed"
        conversation:  List of message dicts captured from stream events
        instruction:   Original task instruction text
        num_turns:     Number of agent turns completed

    Returns:
        Dict with {passed, feedback, details} from test.py, or None if test.py
        is unavailable.
    """
    test_py_path = task_dir / "test.py"
    if not test_py_path.exists():
        return None

    # Dynamic import with unique module name to avoid caching issues
    module_name = f"task_test_{task_dir.name.replace('-', '_').replace('.', '_')}"
    # Remove from sys.modules if previously loaded (important for reruns)
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

    # Build the result dict that test.py expects
    # (matches CocoaAgent framework's TaskExecutor.run_task() output format)
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

    Supported formats (checked in priority order):
        1. <answer>ANSWER</answer>               — explicit XML-style tags
        2. ANSWER: value                          — "ANSWER:" prefix on its own line
        3. **Expected Answer[...]:** value        — bold "Expected Answer" label
        4. ### Final Answer [...]\ncontent         — markdown heading "Final Answer"
        5. ## Answer\ncontent                      — markdown heading "Answer"
        6. **Label:**\n**value**                   — bold label followed by bold value
        7. Final Answer: value                     — inline "Final Answer" in text

    Returns the answer string, or None if extraction fails.
    """
    sol_path = task_dir / SOLUTION_FILENAME
    if not sol_path.exists():
        return None

    text = sol_path.read_text(encoding="utf-8", errors="replace")

    # ── Priority 1: <answer>...</answer> tags — highest priority ──
    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # ── Priority 2: "ANSWER: value" standalone line ──
    m = re.search(r"^\s*ANSWER\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # ── Priority 3a: **Expected Answer[...]:** value (same line) ──
    m = re.search(
        r"\*\*Expected\s+Answer[^*]*\*\*\s*:?\s*(.+)",
        text,
        re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        val = re.sub(r"^\*\*(.+)\*\*$", r"\1", val)
        if val:
            return val

    # ── Priority 3b: **Expected Answer[...]:** with value on next line(s) ──
    m = re.search(
        r"\*\*Expected\s+Answer[^*]*\*\*\s*:?\s*\n\s*(.+?)(?:\n\s*\n|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        val = re.sub(r"^\*\*(.+)\*\*$", r"\1", val)
        if val:
            return val

    # ── Priority 4: Markdown heading "Final Answer" ──
    m = re.search(
        r"#{1,6}\s*Final\s+Answer\b[^\n]*\n(.*?)(?=\n\s*#{1,6}\s|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        answer = m.group(1).strip()
        if answer:
            return answer

    # ── Priority 5: Markdown heading "Answer" (without "Final") ──
    m = re.search(
        r"#{1,6}\s*Answer\s*\n(.*?)(?=\n\s*#{1,6}\s|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        answer = m.group(1).strip()
        if answer:
            return answer

    # ── Priority 6: Bold label on one line, bold value on next line ──
    bold_pairs = re.findall(
        r"\*\*[^*]+\*\*\s*\n\s*\*\*([^*]+)\*\*",
        text,
    )
    if bold_pairs:
        return bold_pairs[-1].strip()

    # ── Priority 7: "Final Answer" in running text ──
    m = re.search(
        r"Final\s+Answer\s*[:\-]\s*(.+?)(?:\n\s*\n|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        answer = m.group(1).strip()
        if answer:
            return answer

    return None


# =============================================================================
# Workspace Isolation
# =============================================================================

def create_workspace(task_dir: Path, tmp_root: str) -> Path:
    """
    Copy the entire task folder into a temp directory, EXCLUDING files that
    contain answers (solution.md, test.py, evaluation.md).

    This prevents Claude Code from physically accessing any answer files.
    """
    dest = Path(tmp_root) / task_dir.name
    shutil.copytree(
        task_dir,
        dest,
        ignore=shutil.ignore_patterns(*WORKSPACE_EXCLUDE),
    )
    return dest


# =============================================================================
# Claude Answer Extraction (from Claude's response)
# =============================================================================

def extract_claude_answer(text: str) -> Optional[str]:
    """
    Parse Claude's response text and extract the answer from <answer> tags.
    Falls back to returning the last non-empty line if no tags found.
    """
    if not text:
        return None

    # Look for <answer>...</answer>
    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Fallback: last non-empty line
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        return lines[-1]

    return None


# =============================================================================
# Answer Comparison (FALLBACK — when test.py is not available)
# =============================================================================

def normalize(s: str) -> str:
    """Normalize a string for comparison: lowercase, strip, collapse whitespace."""
    s = s.strip().lower()
    s = s.rstrip(".,;:!?")
    s = re.sub(r"\s+", " ", s)
    return s


def compare_answers(
    claude_answer: Optional[str],
    expected: Optional[str],
) -> Optional[bool]:
    """
    Compare Claude's answer with the expected answer (fallback method).

    Returns:
        True  — answers match
        False — answers clearly don't match
        None  — cannot determine (missing answer on either side)
    """
    if claude_answer is None or expected is None:
        return None

    a = normalize(claude_answer)
    b = normalize(expected)

    if not a or not b:
        return None

    # Exact match
    if a == b:
        return True

    # Numeric equality
    try:
        if abs(float(a) - float(b)) < 1e-9:
            return True
    except (ValueError, OverflowError):
        pass

    # Containment check for short answers
    if len(b) <= 60 and b in a:
        return True
    if len(a) <= 60 and a in b:
        return True

    return False


# =============================================================================
# Build the Prompt
# =============================================================================

def build_prompt(task_yaml_content: str) -> str:
    """
    Construct the prompt that will be sent to Claude Code via `claude -p`.
    """
    return (
        "You are solving a benchmark task. "
        "The current working directory contains the task files.\n\n"
        "Instructions:\n"
        "1. Read the task description below carefully.\n"
        "2. List and examine any other files in the current directory that may be relevant "
        "(data files, images, code, CSVs, etc.).\n"
        "3. Solve the task step by step. Write and run code if needed.\n"
        "4. When you have your final answer, you MUST output it using EXACTLY this format:\n"
        "   <answer>YOUR_ANSWER_HERE</answer>\n\n"
        "CRITICAL RULE: Do NOT search for, read, or access any file named 'solution.md', "
        "'test.py', or 'evaluation.md'. They do not exist in your workspace.\n\n"
        "--- TASK DESCRIPTION (from task.yaml) ---\n"
        f"{task_yaml_content}\n"
        "--- END TASK DESCRIPTION ---\n"
    )


# =============================================================================
# Run a Single Task
# =============================================================================

def run_single_task(
    task_dir: Path,
    workspace: Path,
    model: Optional[str] = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_budget: Optional[float] = None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    verbose: bool = False,
) -> dict:
    """
    Invoke `claude -p` on a single task inside the isolated workspace.
    Uses Popen with stream-json for real-time output and proper timeout handling.

    Returns a dict containing:
        answer, raw_result, conversation, elapsed, exit_code, cost_usd,
        num_turns, full_json, stderr, error
    """
    # Read task description from workspace (NOT from original dir)
    task_text = (workspace / TASK_FILENAME).read_text(
        encoding="utf-8", errors="replace"
    )
    prompt = build_prompt(task_text)

    # Assemble the CLI command
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions",
    ]

    if model:
        cmd += ["--model", model]

    if max_budget is not None:
        cmd += ["--max-budget-usd", str(max_budget)]

    if verbose:
        print(f"\n    [CMD] claude -p '...' --output-format stream-json --verbose "
              f"--max-turns {max_turns} --dangerously-skip-permissions"
              + (f" --model {model}" if model else ""))
        print(f"    [CWD] {workspace}")

    t0 = time.time()
    stdout_chunks = []
    stderr_chunks = []
    last_result_text = ""
    cost_usd = None
    num_turns = None
    conversation = []  # Capture conversation for test.py evaluation
    proc = None

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Read stderr in a background thread so it doesn't block
        def read_stderr():
            try:
                for line in proc.stderr:
                    stderr_chunks.append(line)
            except Exception:
                pass

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        # Read stdout line by line (stream-json = one JSON object per line)
        deadline = t0 + timeout_sec
        for line in proc.stdout:
            stdout_chunks.append(line)
            now = time.time()

            # Parse each stream-json line for progress display
            line_stripped = line.strip()
            if line_stripped:
                try:
                    event = json.loads(line_stripped)
                    event_type = event.get("type", "")

                    if event_type == "result":
                        # Final result message
                        last_result_text = event.get("result", "")
                        cost_usd = event.get("cost_usd")
                        if cost_usd is None:
                            cost_usd = event.get("total_cost_usd")
                        num_turns = event.get("num_turns")
                        if verbose:
                            print(f"\n    [DONE] cost=${cost_usd}, turns={num_turns}")

                    elif event_type == "assistant":
                        msg = event.get("message", {})
                        content_blocks = msg.get("content", [])
                        text_parts = []
                        tool_calls = []
                        for block in content_blocks:
                            if block.get("type") == "text":
                                text_parts.append(block["text"])
                                if verbose:
                                    text_preview = block["text"][:200].replace("\n", " ")
                                    print(f"    [CLAUDE] {text_preview}")
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "?")
                                tool_input = block.get("input", {})
                                tool_calls.append({
                                    "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
                                    },
                                })
                                if verbose:
                                    print(f"    [TOOL]   {tool_name}: {str(tool_input)[:100]}")

                        # Build conversation entry for test.py
                        conv_entry = {
                            "role": "assistant",
                            "content": "\n".join(text_parts),
                        }
                        if tool_calls:
                            conv_entry["tool_calls"] = tool_calls
                        conversation.append(conv_entry)

                    elif event_type == "tool_result":
                        content = event.get("content", "")
                        if isinstance(content, list):
                            # Handle structured content blocks
                            parts = []
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    parts.append(c.get("text", ""))
                                else:
                                    parts.append(str(c))
                            content = "\n".join(parts)
                        conversation.append({
                            "role": "tool",
                            "content": str(content),
                        })
                        if verbose:
                            preview = str(content)[:200].replace("\n", " ")
                            print(f"    [TRESULT] {preview}")

                except json.JSONDecodeError:
                    if verbose:
                        print(f"    [RAW] {line_stripped[:120]}")

            # Check timeout
            if now > deadline:
                proc.kill()
                proc.wait()
                elapsed = time.time() - t0
                answer = extract_claude_answer(last_result_text)
                return {
                    "answer": answer,
                    "raw_result": last_result_text if last_result_text else "(timeout, partial captured)",
                    "conversation": conversation,
                    "elapsed": round(elapsed, 2),
                    "exit_code": -1,
                    "cost_usd": cost_usd,
                    "num_turns": num_turns,
                    "full_json": {},
                    "stderr": "".join(stderr_chunks)[:2000],
                    "error": f"Timeout after {timeout_sec}s (partial output captured)",
                }

        # Process finished normally
        proc.wait()
        stderr_thread.join(timeout=5)
        elapsed = time.time() - t0

        # If we didn't get a result from streaming events, scan collected lines
        if not last_result_text:
            full_stdout = "".join(stdout_chunks)
            for scan_line in reversed(full_stdout.strip().splitlines()):
                scan_line = scan_line.strip()
                if not scan_line:
                    continue
                try:
                    final_obj = json.loads(scan_line)
                    if final_obj.get("type") == "result":
                        last_result_text = final_obj.get("result", "")
                        cost_usd = final_obj.get("cost_usd")
                        if cost_usd is None:
                            cost_usd = final_obj.get("total_cost_usd")
                        num_turns = final_obj.get("num_turns")
                        break
                except json.JSONDecodeError:
                    continue

        answer = extract_claude_answer(last_result_text)

        return {
            "answer": answer,
            "raw_result": last_result_text,
            "conversation": conversation,
            "elapsed": round(elapsed, 2),
            "exit_code": proc.returncode,
            "cost_usd": cost_usd,
            "num_turns": num_turns,
            "full_json": {},
            "stderr": "".join(stderr_chunks)[:2000],
            "error": None,
        }

    except FileNotFoundError:
        return _error_result(0, (
            "'claude' command not found. "
            "Is Claude Code CLI installed and in PATH?"
        ))

    except Exception as exc:
        if proc is not None:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass
        return _error_result(time.time() - t0, str(exc))


def _error_result(elapsed: float, error_msg: str) -> dict:
    """Helper to build a standardized error result dict."""
    return {
        "answer": None,
        "raw_result": "",
        "conversation": [],
        "elapsed": round(elapsed, 2),
        "exit_code": -1,
        "cost_usd": None,
        "num_turns": None,
        "full_json": {},
        "stderr": "",
        "error": error_msg,
    }


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
    if not s:
        return "(none)"
    s = s.replace("\n", " ")
    return s[:length] + "..." if len(s) > length else s


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CocoaBench Benchmark Runner — run Claude Code on benchmark tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test with 2 tasks
  python Claude_Code_run_benchmark.py --limit 2

  # Run only specific tasks
  python Claude_Code_run_benchmark.py --tasks arrow-hunt nonogram-2

  # Full run with a specific model
  python Claude_Code_run_benchmark.py --model sonnet

  # Resume after interruption (skip already-completed tasks)
  python Claude_Code_run_benchmark.py --skip-existing

  # Dry run — just list tasks, don't execute
  python Claude_Code_run_benchmark.py --dry-run

  # Verbose output for debugging
  python Claude_Code_run_benchmark.py --limit 1 --verbose
        """,
    )

    parser.add_argument(
        "--dir", default=DEFAULT_BENCH_DIR,
        help=f"Path to the benchmark task directory (default: {DEFAULT_BENCH_DIR})",
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write results (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model to use (e.g. sonnet, opus). Omit for Claude Code default.",
    )
    parser.add_argument(
        "--max-turns", type=int, default=DEFAULT_MAX_TURNS,
        help=f"Max agentic turns per task (default: {DEFAULT_MAX_TURNS})",
    )
    parser.add_argument(
        "--max-budget", type=float, default=None,
        help="Max cost in USD per task (default: no limit). e.g. --max-budget 2.0",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SEC,
        help=f"Timeout in seconds per task (default: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument(
        "--tasks", nargs="+", default=None,
        help="Only run these specific task folder names (space-separated)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only run the first N tasks (useful for testing)",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip tasks that already have a result JSON in the output dir",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List discovered tasks and exit without running anything",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print extra debug info (commands, full answers on mismatch)",
    )

    args = parser.parse_args()

    bench_dir = Path(args.dir)
    out_dir = Path(args.out)

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------
    print()
    print("=" * 62)
    print("   CocoaBench Runner for Claude Code")
    print("=" * 62)

    # ------------------------------------------------------------------
    # Verify claude CLI
    # ------------------------------------------------------------------
    try:
        ver_proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        cli_version = ver_proc.stdout.strip() or "(unknown version)"
        print(f"   Claude CLI  : {cli_version}")
    except FileNotFoundError:
        print("   ERROR: 'claude' command not found!")
        print("   Install Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("   WARNING: 'claude --version' timed out. Continuing anyway...")

    # ------------------------------------------------------------------
    # Discover tasks
    # ------------------------------------------------------------------
    all_tasks = find_tasks(bench_dir)
    print(f"   Bench dir   : {bench_dir.resolve()}")
    print(f"   Tasks found : {len(all_tasks)}")
    print(f"   Output dir  : {out_dir.resolve()}")
    print(f"   Model       : {args.model or '(default)'}")
    print(f"   Max turns   : {args.max_turns}")
    print(f"   Max budget  : {'$' + str(args.max_budget) if args.max_budget else '(no limit)'}")
    print(f"   Timeout     : {args.timeout}s per task")
    print(f"   Eval method : test.py (primary) + solution.md (fallback)")

    # ------------------------------------------------------------------
    # Filter tasks
    # ------------------------------------------------------------------
    tasks = all_tasks[:]

    if args.tasks:
        requested = set(args.tasks)
        tasks = [t for t in tasks if t.name in requested]
        missing = requested - {t.name for t in tasks}
        if missing:
            print(f"   WARNING: requested tasks not found: {missing}")
        print(f"   Filtered    : {len(tasks)} tasks selected by name")

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

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n   [DRY RUN] Task list:\n")
        for i, t in enumerate(tasks, 1):
            has_test = "✓" if (t / "test.py").exists() else "✗"
            has_sol = "✓" if (t / SOLUTION_FILENAME).exists() else "✗"
            print(f"   {i:4d}. {t.name:45s}  test.py={has_test}  solution.md={has_sol}")
        print(f"\n   Total: {len(tasks)} tasks. Use without --dry-run to execute.\n")
        return

    if not tasks:
        print("\n   Nothing to run. Done.\n")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------
    print(f"\n   Starting {len(tasks)} tasks...\n")

    results: list[dict] = []
    total_cost = 0.0

    with tempfile.TemporaryDirectory(prefix="cocoa_bench_") as tmp_root:
        for idx, task_dir in enumerate(tasks, 1):
            name = task_dir.name
            print(f"   [{idx:3d}/{len(tasks)}] {name:40s} ", end="", flush=True)

            # 1. Create isolated workspace (no solution.md, no test.py)
            workspace = create_workspace(task_dir, tmp_root)

            # 2. Run Claude Code
            result = run_single_task(
                task_dir=task_dir,
                workspace=workspace,
                model=args.model,
                max_turns=args.max_turns,
                max_budget=args.max_budget,
                timeout_sec=args.timeout,
                verbose=args.verbose,
            )

            # 3. Clean up workspace to save disk
            shutil.rmtree(workspace, ignore_errors=True)

            # 4. Evaluate — primary: test.py, fallback: solution.md
            # Determine task status for test.py
            has_error = bool(result.get("error"))
            exit_ok = result.get("exit_code", -1) == 0
            task_status = "success" if (not has_error and exit_ok) else "failed"

            # Read task instruction for test.py
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
                # PRIMARY: test.py evaluation succeeded
                passed = test_py_output.get("passed", False)
                feedback = test_py_output.get("feedback", "")
                eval_details = test_py_output.get("details", {})
                eval_method = "test.py"
                claude_ans = eval_details.get("output_answer") or result.get("answer")
                expected_ans = eval_details.get("expected_answer")
            else:
                # FALLBACK: no test.py, use solution.md string comparison
                expected_ans = extract_expected_answer(task_dir)
                claude_ans = result.get("answer")
                match = compare_answers(claude_ans, expected_ans)
                passed = match  # True, False, or None
                feedback = ""
                eval_details = {}
                eval_method = "solution.md"

            if result.get("cost_usd"):
                total_cost += result["cost_usd"]

            # 5. Build record
            record = {
                "task": name,
                "passed": passed,
                "eval_method": eval_method,
                "feedback": feedback,
                "claude_answer": claude_ans,
                "expected_answer": expected_ans,
                "elapsed_seconds": result.get("elapsed"),
                "cost_usd": result.get("cost_usd"),
                "num_turns": result.get("num_turns"),
                "exit_code": result.get("exit_code"),
                "error": result.get("error"),
                "eval_details": eval_details,
                "timestamp": datetime.now().isoformat(),
            }
            results.append(record)

            # 6. Save per-task detail file
            detail = {
                **record,
                "raw_result": (result.get("raw_result") or "")[:5000],
                "stderr": result.get("stderr", ""),
            }
            detail_path = out_dir / f"{name}.json"
            detail_path.write_text(
                json.dumps(detail, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # 7. Print one-line status
            icon = status_icon(passed)
            parts = [f"{result.get('elapsed', 0):.0f}s"]
            if result.get("cost_usd"):
                parts.append(f"${result['cost_usd']:.3f}")
            if result.get("num_turns"):
                parts.append(f"{result['num_turns']}t")
            parts.append(f"[{eval_method}]")
            if result.get("error"):
                parts.append(f"ERR: {result['error'][:40]}")
            print(f"{icon}  {', '.join(parts)}")

            # Show details on failure or verbose
            if args.verbose or passed is False:
                print(f"            got:      \"{truncate(claude_ans)}\"")
                print(f"            expected: \"{truncate(expected_ans)}\"")
                if feedback:
                    for fb_line in feedback.splitlines()[:5]:
                        print(f"            {fb_line}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
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

    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "model": args.model or "default",
        "benchmark_dir": str(bench_dir),
        "total_tasks": total,
        "passed": n_passed,
        "failed": n_failed,
        "unknown_or_missing": n_unknown,
        "errors": n_errors,
        "evaluable": evaluable,
        "accuracy_pct": accuracy,
        "eval_by_test_py": n_test_py,
        "eval_by_solution_md": n_fallback,
        "total_cost_usd": round(total_cost, 4),
        "avg_seconds_per_task": avg_time,
        "config": {
            "max_turns": args.max_turns,
            "max_budget_usd": args.max_budget,
            "timeout_sec": args.timeout,
        },
        "per_task": results,
    }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

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
    print(f"   💰 Total cost     : ${total_cost:.4f}")
    print(f"   ⏱️  Avg time       : {avg_time}s / task")
    print(f"   🧪 Eval: test.py  : {n_test_py} tasks")
    print(f"   📄 Eval: fallback : {n_fallback} tasks")
    print(f"   📁 Full results   : {summary_path}")
    print("=" * 62)
    print()


# =============================================================================
# Entry
# =============================================================================

if __name__ == "__main__":
    main()