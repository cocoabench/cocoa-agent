"""
Main inference script for running model inference in the agent environment.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

from agents import BaseAgent, CocoaAgent, OpenAIDeepResearchAgent, GeminiDeepResearchAgent
from executor.utils import setup_logging, load_config, get_logger
from decrypt import decrypt_file_to_memory, read_canary


def parse_arguments() -> dict:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run model inference on tasks")
    parser.add_argument("--config", type=str, default="config.json",
                       help="Path to configuration file")
    parser.add_argument("--tasks-dir", type=str, default="tasks/",
                       help="Path to tasks directory (containing task subdirectories)")
    parser.add_argument("--output-dir", type=str, default="results/",
                       help="Output directory for results (one JSON file per task)")
    parser.add_argument("--model", type=str,
                       help="Override model name from config")

    return parser.parse_args()


def load_tasks(tasks_dir: str, use_encrypted: bool = False) -> List[Dict[str, Any]]:
    """Load tasks from directory structure (tasks/task-name/task.yaml or task.yaml.enc).
    
    Args:
        tasks_dir: Path to tasks directory
        use_encrypted: If True, load from encrypted .enc files (decrypt to memory only)
                      If False, load from plaintext .yaml files
    
    Returns:
        List of task dictionaries
    """
    logger = get_logger("inference")
    tasks = []
    tasks_path = Path(tasks_dir)

    mode = "encrypted" if use_encrypted else "plaintext"
    logger.info(f"Loading tasks from {tasks_dir} (mode: {mode})")

    if not tasks_path.is_dir():
        raise ValueError(f"Tasks directory not found: {tasks_dir}")

    # Iterate through task subdirectories
    for task_dir in sorted(tasks_path.iterdir()):
        if not task_dir.is_dir():
            continue

        if use_encrypted:
            # Load from encrypted file (decrypt to memory only)
            task_file_enc = task_dir / "task.yaml.enc"
            if not task_file_enc.exists():
                logger.warning(f"No task.yaml.enc found in {task_dir}, skipping")
                continue
            
            # Read canary for decryption
            canary = read_canary(task_dir)
            if canary is None:
                logger.warning(f"No canary.txt found in {task_dir}, skipping")
                continue
            
            try:
                # Decrypt to memory
                task_yaml_content = decrypt_file_to_memory(task_file_enc, canary)
                task_data = yaml.safe_load(task_yaml_content)
            except Exception as e:
                logger.error(f"Failed to decrypt task.yaml.enc in {task_dir}: {e}")
                continue
        else:
            # Load from plaintext file
            task_file = task_dir / "task.yaml"
            if not task_file.exists():
                logger.warning(f"No task.yaml found in {task_dir}, skipping")
                continue

            with open(task_file, 'r') as f:
                task_data = yaml.safe_load(f)

        if task_data is None:
            logger.warning(f"Empty task data in {task_dir}, skipping")
            continue

        # Add task directory path and test file path
        task_data["task_dir"] = str(task_dir)
        task_data["task_name"] = task_dir.name
        
        # Check for test file (encrypted or plaintext based on mode)
        if use_encrypted:
            test_file_enc = task_dir / "test.py.enc"
            task_data["test_file_path"] = str(test_file_enc) if test_file_enc.exists() else None
            task_data["use_encrypted"] = True
        else:
            test_file = task_dir / "test.py"
            task_data["test_file_path"] = str(test_file) if test_file.exists() else None
            task_data["use_encrypted"] = False

        tasks.append(task_data)

    logger.info(f"Loaded {len(tasks)} tasks from {tasks_dir}")
    return tasks


def main():
    """Main function."""
    args = parse_arguments()

    config = load_config(args.config)

    # Setup logging with specified level FIRST before getting any loggers
    log_level = config.get("log_level", "INFO")
    setup_logging(log_level)

    logger = get_logger("inference")
    logger.info("Starting inference")

    if args.model:
        # Override model in controller config
        config["controller"]["args"]["model"] = args.model
        logger.info(f"Model overridden to: {args.model}")

    os.makedirs(args.output_dir, exist_ok=True)

    # Check if we should use encrypted tasks
    use_encrypted = config.get("use_encrypted_tasks", False)
    logger.info(f"Use encrypted tasks: {use_encrypted}")

    # Select agent based on configuration
    agent_type = config.get("agent_type", "cocoa")
    logger.info(f"Using agent type: {agent_type}")
    
    if agent_type == "openai_deep_research":
        agent = OpenAIDeepResearchAgent(config)
    elif agent_type == "gemini_deep_research":
        agent = GeminiDeepResearchAgent(config)
    elif agent_type == "cocoa":
        agent = CocoaAgent(config)
    else:
        raise ValueError(f"Unknown agent type: {agent_type}")

    tasks = load_tasks(args.tasks_dir, use_encrypted=use_encrypted)

    for i, task in enumerate(tasks, 1):
        task_name = task.get("task_name", f"task_{i}")
        logger.info(f"Processing task {i}/{len(tasks)}: {task_name}")

        agent.setup_environment(task)
        try:
            result = agent.run_task(task)

            # Run test if available
            test_result = agent.run_eval(task, result)
            if test_result is not None:
                result["eval"] = test_result

            # Save result to task-specific JSON file
            output_file = Path(args.output_dir) / f"{task_name}.json"
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            logger.debug(f"Task {task_name} result saved to {output_file}")
        except Exception as e:
            logger.error(f"Task {task_name} failed with error: {e}")
            # Save error result
            error_result = {
                "status": "error",
                "error": str(e),
                "task_name": task_name
            }
            output_file = Path(args.output_dir) / f"{task_name}.json"
            with open(output_file, 'w') as f:
                json.dump(error_result, f, indent=2)
        finally:
            agent.cleanup_environment()

    logger.info(f"Processed {len(tasks)} tasks. Results saved to {args.output_dir}")

    # Calculate statistics
    total_tasks = 0
    passed_tasks = 0
    error_tasks = 0
    passed_list = []
    error_list = []
    
    output_path = Path(args.output_dir)
    if output_path.exists():
        for json_file in output_path.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    total_tasks += 1
                    if data.get("status") == "error":
                        error_tasks += 1
                        error_list.append(json_file.stem)
                    elif data.get("eval", {}).get("passed", False) is True:
                        passed_tasks += 1
                        passed_list.append(json_file.stem)
            except Exception as e:
                logger.error(f"Error reading {json_file}: {e}")

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
    
    stats_file = output_path / "statistics.txt"
    with open(stats_file, 'w') as f:
        f.write(stats_content)
        
    logger.info(f"Statistics saved to {stats_file}")


if __name__ == "__main__":
    main()