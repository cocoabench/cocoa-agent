"""
Parallel inference runner for CocoaAgent.

This script partitions tasks across multiple worker processes. Each worker runs
the existing `inference_main.py` entrypoint with its own sandbox port, so every
worker can launch an independent Docker-backed sandbox environment safely.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CocoaAgent inference in parallel with one worker per sandbox port."
    )
    parser.add_argument("--config", type=str, required=True, help="Path to JSON config file")
    parser.add_argument("--tasks-dir", type=str, required=True, help="Directory containing task subdirectories")
    parser.add_argument("--output-dir", type=str, required=True, help="Final merged output directory")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--base-port", type=int, default=8084, help="Starting sandbox port")
    parser.add_argument("--model", type=str, help="Optional model override passed to inference_main.py")
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run all tasks even if a successful result already exists in the final output directory",
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        default=".parallel_run",
        help="Directory for temporary worker configs, logs, and intermediate results",
    )
    return parser.parse_args()


def list_task_dirs(tasks_dir: Path) -> List[Path]:
    return sorted(path for path in tasks_dir.iterdir() if path.is_dir())


def should_run_task(task_dir: Path, output_dir: Path) -> bool:
    result_file = output_dir / f"{task_dir.name}.json"
    if not result_file.exists():
        return True

    try:
        with open(result_file, "r") as f:
            data = json.load(f)
        return data.get("status") == "error"
    except Exception:
        return True


def partition_tasks(task_dirs: List[Path], worker_count: int) -> List[List[Path]]:
    worker_count = max(1, min(worker_count, len(task_dirs)))
    partitions: List[List[Path]] = [[] for _ in range(worker_count)]
    for index, task_dir in enumerate(task_dirs):
        partitions[index % worker_count].append(task_dir)
    return partitions


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def link_or_copy_task(task_dir: Path, destination: Path) -> None:
    try:
        destination.symlink_to(task_dir.resolve(), target_is_directory=True)
    except OSError:
        shutil.copytree(task_dir, destination)


def prepare_worker_tasks(task_dirs: Iterable[Path], worker_tasks_dir: Path) -> None:
    ensure_clean_dir(worker_tasks_dir)
    for task_dir in task_dirs:
        link_or_copy_task(task_dir, worker_tasks_dir / task_dir.name)


def write_worker_config(config_path: Path, worker_config_path: Path, docker_port: int) -> None:
    with open(config_path, "r") as f:
        config = json.load(f)

    config.setdefault("sandbox", {})
    config["sandbox"]["docker_port"] = docker_port

    with open(worker_config_path, "w") as f:
        json.dump(config, f, indent=2)


def build_worker_command(
    repo_root: Path,
    worker_config_path: Path,
    worker_tasks_dir: Path,
    worker_output_dir: Path,
    model: str | None,
) -> List[str]:
    command = [
        sys.executable,
        "inference_main.py",
        "--config",
        str(worker_config_path),
        "--tasks-dir",
        str(worker_tasks_dir),
        "--output-dir",
        str(worker_output_dir),
        "--run-all",
    ]
    if model:
        command.extend(["--model", model])
    return command


def merge_worker_outputs(worker_output_dirs: Iterable[Path], final_output_dir: Path) -> None:
    final_output_dir.mkdir(parents=True, exist_ok=True)
    for worker_output_dir in worker_output_dirs:
        for json_file in sorted(worker_output_dir.glob("*.json")):
            shutil.copy2(json_file, final_output_dir / json_file.name)


def write_statistics(output_dir: Path) -> None:
    total_tasks = 0
    passed_tasks = 0
    error_tasks = 0
    passed_list: list[str] = []
    error_list: list[str] = []
    grand_total_cost = 0.0
    grand_total_input = 0
    grand_total_output = 0
    grand_total_cached = 0
    per_task_costs: list[tuple[str, float, int]] = []

    for json_file in sorted(output_dir.glob("*.json")):
        try:
            with open(json_file, "r") as f:
                data = json.load(f)
            total_tasks += 1

            if data.get("status") == "error":
                error_tasks += 1
                error_list.append(json_file.stem)
            elif data.get("eval", {}).get("passed", False) is True:
                passed_tasks += 1
                passed_list.append(json_file.stem)

            cost_stats = data.get("api_cost_stats", {})
            task_cost = float(cost_stats.get("total_cost_usd", 0) or 0)
            grand_total_cost += task_cost
            grand_total_input += int(cost_stats.get("total_input_tokens", 0) or 0)
            grand_total_output += int(cost_stats.get("total_output_tokens", 0) or 0)
            grand_total_cached += int(cost_stats.get("total_cached_tokens", 0) or 0)
            if task_cost > 0:
                per_task_costs.append((json_file.stem, task_cost, int(cost_stats.get("api_calls", 0) or 0)))
        except Exception as exc:
            print(f"Error reading {json_file}: {exc}", file=sys.stderr)

    success_rate = (passed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0

    stats_content = (
        f"Total Tasks: {total_tasks}\n"
        f"Passed: {passed_tasks}\n"
        f"Failed: {total_tasks - passed_tasks - error_tasks}\n"
        f"Errors: {error_tasks}\n"
        f"Success Rate: {success_rate:.2f}%\n"
    )

    if passed_list:
        stats_content += "\nPassed Tasks:\n"
        for task_name in sorted(passed_list):
            stats_content += f"  - {task_name}\n"

    if error_list:
        stats_content += "\nError Tasks:\n"
        for task_name in sorted(error_list):
            stats_content += f"  - {task_name}\n"

    stats_content += (
        f"\n--- Cost Summary ---\n"
        f"Grand Total Cost: ${grand_total_cost:.6f}\n"
        f"Total Input Tokens: {grand_total_input}\n"
        f"Total Output Tokens: {grand_total_output}\n"
        f"Total Cached Tokens: {grand_total_cached}\n"
    )

    if per_task_costs:
        stats_content += "\nPer-Task Costs:\n"
        for task_name, task_cost, task_calls in sorted(per_task_costs, key=lambda item: -item[1]):
            stats_content += f"  {task_name}: ${task_cost:.6f} ({task_calls} calls)\n"

    stats_file = output_dir / "statistics.txt"
    with open(stats_file, "w") as f:
        f.write(stats_content)


def main() -> int:
    args = parse_args()

    repo_root = Path(__file__).resolve().parent
    config_path = Path(args.config).resolve()
    tasks_dir = Path(args.tasks_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    work_root = Path(args.work_dir).resolve()

    if not config_path.is_file():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1
    if not tasks_dir.is_dir():
        print(f"Tasks directory not found: {tasks_dir}", file=sys.stderr)
        return 1
    if args.workers < 1:
        print("--workers must be >= 1", file=sys.stderr)
        return 1

    all_task_dirs = list_task_dirs(tasks_dir)
    if not all_task_dirs:
        print(f"No task directories found in {tasks_dir}", file=sys.stderr)
        return 1

    selected_tasks = all_task_dirs if args.run_all else [task for task in all_task_dirs if should_run_task(task, output_dir)]
    if not selected_tasks:
        print("No tasks to run.")
        return 0

    session_dir = work_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir.mkdir(parents=True, exist_ok=True)

    partitions = partition_tasks(selected_tasks, args.workers)
    worker_output_dirs: list[Path] = []
    processes: list[tuple[int, subprocess.Popen[str], Path]] = []

    print(f"Total tasks selected: {len(selected_tasks)}")
    print(f"Launching {len(partitions)} workers")
    print(f"Session directory: {session_dir}")

    for worker_index, worker_tasks in enumerate(partitions):
        worker_dir = session_dir / f"worker_{worker_index}"
        worker_tasks_dir = worker_dir / "tasks"
        worker_output_dir = worker_dir / "output"
        worker_output_dir.mkdir(parents=True, exist_ok=True)
        prepare_worker_tasks(worker_tasks, worker_tasks_dir)

        worker_config_path = worker_dir / "config.json"
        docker_port = args.base_port + worker_index
        write_worker_config(config_path, worker_config_path, docker_port)

        log_path = worker_dir / "worker.log"
        command = build_worker_command(
            repo_root=repo_root,
            worker_config_path=worker_config_path,
            worker_tasks_dir=worker_tasks_dir,
            worker_output_dir=worker_output_dir,
            model=args.model,
        )

        log_file = open(log_path, "w")
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_file.close()

        worker_output_dirs.append(worker_output_dir)
        processes.append((worker_index, process, log_path))
        print(
            f"[worker {worker_index}] pid={process.pid} port={docker_port} "
            f"tasks={len(worker_tasks)} log={log_path}"
        )

    failed_workers: list[int] = []
    for worker_index, process, log_path in processes:
        return_code = process.wait()
        if return_code == 0:
            print(f"[worker {worker_index}] finished successfully")
        else:
            failed_workers.append(worker_index)
            print(f"[worker {worker_index}] failed with exit code {return_code}. See {log_path}", file=sys.stderr)

    merge_worker_outputs(worker_output_dirs, output_dir)
    write_statistics(output_dir)

    print(f"Merged results into {output_dir}")
    print(f"Statistics written to {output_dir / 'statistics.txt'}")

    if failed_workers:
        print(f"Failed workers: {failed_workers}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
