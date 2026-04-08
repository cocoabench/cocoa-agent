"""
Parallel inference runner for CocoaAgent.
"""
import argparse
import json
import multiprocessing as mp
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CocoaAgent inference with a multiprocessing worker pool."
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


def list_task_dirs(tasks_dir: Path) -> list[Path]:
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


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def link_or_copy_task(task_dir: Path, destination: Path) -> None:
    try:
        destination.symlink_to(task_dir.resolve(), target_is_directory=True)
    except OSError:
        shutil.copytree(task_dir, destination)


def write_worker_config(config_path: Path, worker_config_path: Path, docker_port: int) -> None:
    with open(config_path, "r") as f:
        config = json.load(f)

    config.setdefault("sandbox", {})
    config["sandbox"]["docker_port"] = docker_port

    with open(worker_config_path, "w") as f:
        json.dump(config, f, indent=2)


def build_worker_command(
    worker_config_path: Path,
    worker_tasks_dir: Path,
    worker_output_dir: Path,
    model: str | None,
) -> list[str]:
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


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_available_ports(
    count: int,
    start_port: int,
    host: str = "0.0.0.0",
    max_scan: int = 10000,
) -> list[int]:
    if count < 1:
        return []

    ports: list[int] = []
    port = start_port
    upper_bound = start_port + max_scan

    while len(ports) < count and port < upper_bound:
        if is_port_available(port, host=host):
            ports.append(port)
        port += 1

    if len(ports) < count:
        raise RuntimeError(
            f"Unable to find {count} available ports starting from {start_port}. "
            f"Scanned up to {upper_bound - 1}."
        )

    return ports


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

    output_dir.mkdir(parents=True, exist_ok=True)

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

    with open(output_dir / "statistics.txt", "w") as f:
        f.write(stats_content)


@dataclass
class WorkerSlot:
    index: int


@dataclass
class TaskRunPaths:
    task_name: str
    source_dir: Path
    run_dir: Path
    input_dir: Path
    temp_output_dir: Path
    log_path: Path
    config_path: Path
    docker_port: int


def prepare_task_run(task_dir: Path, tasks_root: Path, base_config_path: Path, docker_port: int) -> TaskRunPaths:
    run_dir = tasks_root / task_dir.name
    input_dir = run_dir / "input"
    temp_output_dir = run_dir / "output"
    log_path = run_dir / "run.log"
    config_path = run_dir / "config.json"

    run_dir.mkdir(parents=True, exist_ok=True)
    ensure_clean_dir(input_dir)
    ensure_clean_dir(temp_output_dir)
    link_or_copy_task(task_dir, input_dir / task_dir.name)
    write_worker_config(base_config_path, config_path, docker_port)

    return TaskRunPaths(
        task_name=task_dir.name,
        source_dir=task_dir,
        run_dir=run_dir,
        input_dir=input_dir,
        temp_output_dir=temp_output_dir,
        log_path=log_path,
        config_path=config_path,
        docker_port=docker_port,
    )


def write_fallback_error_result(task: TaskRunPaths, error_message: str) -> Path:
    output_file = task.temp_output_dir / f"{task.task_name}.json"
    error_result = {
        "status": "error",
        "error": error_message,
        "task_name": task.task_name,
    }
    with open(output_file, "w") as f:
        json.dump(error_result, f, indent=2)
    return output_file


def run_task_in_worker(
    slot: WorkerSlot,
    repo_root: Path,
    task: TaskRunPaths,
    model: str | None,
) -> dict[str, str | int]:
    command = build_worker_command(
        worker_config_path=task.config_path,
        worker_tasks_dir=task.input_dir,
        worker_output_dir=task.temp_output_dir,
        model=model,
    )

    started_at = datetime.now().isoformat(timespec="seconds")
    with open(task.log_path, "a") as log_file:
        log_file.write(
            f"\n==== worker={slot.index} pid={os.getpid()} port={task.docker_port} "
            f"task={task.task_name} started_at={started_at} ====\n"
        )
        log_file.flush()
        completed = subprocess.run(
            command,
            cwd=repo_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    output_file = task.temp_output_dir / f"{task.task_name}.json"
    return_code = completed.returncode
    if not output_file.exists():
        output_file = write_fallback_error_result(
            task,
            f"inference_main.py exited with code {completed.returncode} without producing {task.task_name}.json",
        )
        if return_code == 0:
            return_code = 1

    finished_at = datetime.now().isoformat(timespec="seconds")
    return {
        "event": "finished",
        "worker_index": str(slot.index),
        "task_name": task.task_name,
        "return_code": str(return_code),
        "log_path": str(task.log_path),
        "output_file": str(output_file),
        "finished_at": finished_at,
    }


def worker_main(
    slot: WorkerSlot,
    repo_root: Path,
    model: str | None,
    task_queue: mp.Queue,
    result_queue: mp.Queue,
) -> None:
    while True:
        task = task_queue.get()
        if task is None:
            return

        result_queue.put(
            {
                "event": "started",
                "worker_index": str(slot.index),
                "worker_pid": str(os.getpid()),
                "task_name": task.task_name,
                "log_path": str(task.log_path),
                "docker_port": str(task.docker_port),
            }
        )

        try:
            result_queue.put(run_task_in_worker(slot=slot, repo_root=repo_root, task=task, model=model))
        except Exception as exc:
            output_file = write_fallback_error_result(task, f"Worker crashed while running task: {exc}")
            result_queue.put(
                {
                    "event": "finished",
                    "worker_index": str(slot.index),
                    "task_name": task.task_name,
                    "return_code": "1",
                    "log_path": str(task.log_path),
                    "output_file": str(output_file),
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                }
            )


def copy_task_output(task_output_file: Path, final_output_dir: Path) -> None:
    final_output_dir.mkdir(parents=True, exist_ok=True)
    if task_output_file.exists():
        shutil.copy2(task_output_file, final_output_dir / task_output_file.name)


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
    tasks_root = session_dir / "tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    worker_count = max(1, min(args.workers, len(selected_tasks)))
    worker_slots = [WorkerSlot(index=worker_index) for worker_index in range(worker_count)]
    task_ports = find_available_ports(count=len(selected_tasks), start_port=args.base_port)
    task_runs = [
        prepare_task_run(
            task_dir=task_dir,
            tasks_root=tasks_root,
            base_config_path=config_path,
            docker_port=task_ports[task_index],
        )
        for task_index, task_dir in enumerate(selected_tasks)
    ]

    print(f"Total tasks selected: {len(task_runs)}")
    print(f"Launching {worker_count} workers")
    print(f"Session directory: {session_dir}")
    print(f"Allocated task ports from {task_ports[0]} to {task_ports[-1]}")

    ctx = mp.get_context("spawn")
    task_queue: mp.Queue = ctx.Queue()
    result_queue: mp.Queue = ctx.Queue()

    for task in task_runs:
        task_queue.put(task)
    for _ in range(worker_count):
        task_queue.put(None)

    processes: list[mp.Process] = []
    for slot in worker_slots:
        process = ctx.Process(
            target=worker_main,
            args=(slot, repo_root, args.model, task_queue, result_queue),
            name=f"parallel-worker-{slot.index}",
        )
        process.start()
        processes.append(process)
        print(f"[worker {slot.index}] pid={process.pid} ready")

    completed_tasks = 0
    completed_task_names: set[str] = set()
    failed_tasks: list[str] = []

    # Workers publish `started` and `finished` events so progress is visible while
    # results are still being produced into the shared final output directory.
    while completed_tasks < len(task_runs):
        try:
            event = result_queue.get(timeout=1)
        except Empty:
            if not any(process.is_alive() for process in processes):
                print("All workers exited before all tasks finished.", file=sys.stderr)
                break
            continue

        if event["event"] == "started":
            print(
                f"[worker {event['worker_index']}] pid={event['worker_pid']} "
                f"port={event['docker_port']} task={event['task_name']} log={event['log_path']}"
            )
            continue

        completed_tasks += 1
        completed_task_names.add(event["task_name"])

        output_file = Path(event["output_file"])
        copy_task_output(output_file, output_dir)
        write_statistics(output_dir)

        if int(event["return_code"]) == 0:
            print(
                f"[worker {event['worker_index']}] finished task={event['task_name']} "
                f"({completed_tasks}/{len(task_runs)})"
            )
        else:
            failed_tasks.append(event["task_name"])
            print(
                f"[worker {event['worker_index']}] task={event['task_name']} failed "
                f"with exit code {event['return_code']}. See {event['log_path']}",
                file=sys.stderr,
            )

    for process in processes:
        process.join()

    crashed_workers = [process.name for process in processes if process.exitcode not in (0, None)]
    missing_tasks = sorted(task.task_name for task in task_runs if task.task_name not in completed_task_names)

    write_statistics(output_dir)
    print(f"Results written incrementally to {output_dir}")
    print(f"Statistics written to {output_dir / 'statistics.txt'}")

    if crashed_workers:
        print(f"Workers crashed unexpectedly: {crashed_workers}", file=sys.stderr)
    if missing_tasks:
        print(f"Tasks with no completion event: {missing_tasks}", file=sys.stderr)
    if failed_tasks:
        print(f"Failed tasks: {failed_tasks}", file=sys.stderr)

    if crashed_workers or missing_tasks or failed_tasks:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
