# Cocoa-Agent

Cocoa-Agent is an agent framework for building and evaluating general digital agents. It provides seamless integration with [AIO Sandbox](https://github.com/agent-infra/sandbox), an all-in-one Docker environment. It equips agents with a full suite of tools—browser automation, terminal access, file operations, and code interpreters—enabling them to operate like human developers in realistic settings. Our framework is model-agnostic, and we provide example scripts for running agents with both open-source LLMs such as [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL) and commercial models such as [GPT-5.1](https://openai.com/index/gpt-5-1/), on the example task of [CocoaBench](https://cocoabench.github.io/). To support robust evaluation at scale, cocoa-agent implements both dynamic runtime tests for verifying computational correctness and lightweight static-matching checks for deterministic answers.

## Overview

This framework provides:

- **Model-agnostic execution** - Works with any OpenAI-compatible LLM or human controllers
- **Comprehensive tool suite** - Browser automation, terminal, file operations, code interpretation
- **Scalable evaluation** - Dynamic runtime tests and lightweight static-matching checks
- **Execution tracking** - Full conversation history and action traces for analysis
- **Docker isolation** - Sandboxed task environments with custom configurations

## Quick Start

### Running Tasks

Execute all tasks in a directory using the main entry point:

```bash
python inference_main.py \
  --config configs/default_gpt.json \
  --tasks-dir tasks/ \
  --output-dir results/
```

**Command-line Options:**
- `--config CONFIG_FILE`: Path to configuration file (default: `config.json`)
- `--tasks-dir TASKS_DIR`: Directory containing task subdirectories (default: `tasks/`)
- `--output-dir OUTPUT_DIR`: Output directory for results JSON files (default: `results/`)
- `--model MODEL_NAME`: Override model name from config

### Configuration File Format

**Example `configs/default_gpt.json`:**

```json
{
  "log_level": "INFO",
  "use_encrypted_tasks": false,
  "controller": {
    "type": "llm",
    "args": {
      "model": "gpt-5.1",
      "base_url": "",
      "api_key": "sk-proj-..."
    }
  },
  "sandbox": {
    "client_type": "unified",
    "docker_port": 8084,
    "max_iterations": 30
  }
}
```

**Configuration Keys:**

| Key | Type | Description |
|-----|------|-------------|
| `log_level` | string | Logging verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)|
| `use_encrypted_tasks` | bool | Enable encrypted task files (default: false) |
| `controller.type` | string | Agent type: "llm" (AI model) or "human" (interactive) |
| `controller.args.model` | string | Model identifier (e.g., "gpt-5.1", "Qwen3-VL") |
| `controller.args.base_url` | string | API endpoint (empty for OpenAI, required for local servers) |
| `controller.args.api_key` | string | Authentication token |
| `sandbox.client_type` | string | Sandbox mode: "unified" (all tools) or "browser" (UI only) |
| `sandbox.docker_port` | int | Host port for sandbox access (default: 8080) |
| `sandbox.max_iterations` | int | Maximum iterations per task before timeout |

## Evaluation

The system uses a **host-side evaluation approach** where the `test()` function in `test.py` validates task results.

### Evaluation Method: `test.py`

The evaluation script runs on the host machine after task completion. The framework:

1. Loads the `test()` function from `test.py` in the task directory
2. Calls `test(result)` with the complete execution result dictionary
3. Expects a dictionary return value with evaluation results

**Function Signature:**
```python
def test(result: dict) -> dict:
    """Evaluate task results after execution.

    Args:
        result: Complete execution result containing:
            - conversation: Full message history with controller
            - execution_trace: All actions and their outputs
            - status: Task status ("success" or "failed")
            - instruction: Original task instruction
            - iterations: Number of iterations completed
            - sandbox: Sandbox configuration (docker_port, etc.)

    Returns:
        Dictionary with:
            - passed (bool): Whether task passed evaluation
            - feedback (str): Human-readable evaluation message
            - details (dict, optional): Additional metrics
    """
```

**Return Format:**
```python
{
    "passed": True,                    # Required: Whether task passed
    "feedback": "Task completed successfully",  # Required: Human-readable message
    "details": {                       # Optional: Additional metrics
        "key1": "value1",
        "key2": "value2"
    }
}
```

**Result Dictionary Contents:**
```python
result = {
    "task_name": "task-name",
    "instruction": "Task instruction...",
    "status": "success",  # or "failed"
    "iterations": 5,
    "conversation": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ],
    "execution_trace": [
        {
            "action": {"action_type": "shell", "command": "ls"},
            "feedback": {"done": False, "message": "..."}
        }
    ],
    "sandbox": {
        "docker_port": 8080,
        "client_type": "unified"
    }
}
```

### Sandbox API for Host-Side Scripts

Call Sandbox APIs from `test.py` to inspect container state:

```python
from pathlib import Path
import sys

# Initialize sandbox client
sandbox_sdk_path = Path(__file__).parent.parent / "sandbox" / "sdk" / "python"
if sandbox_sdk_path.exists():
    sys.path.insert(0, str(sandbox_sdk_path))
    from agent_sandbox import Sandbox

docker_port = result.get("sandbox", {}).get("docker_port", 8080)
sandbox = Sandbox(base_url=f"http://localhost:{docker_port}")

# Read file (text files, e.g., .txt, .md, .tex, etc.)
content = sandbox.file.read_file(file="/home/gem/output.txt").data.content

# List directory
entries = sandbox.file.list_path(path="/home/gem").data.entries

# Download file (binary files, e.g., .jpg, .png, .doc, .pptx, etc.)
binary_data = sandbox.file.download_file(path="/home/gem/report.pdf")
```

**Common File APIs:**

| Capability      | API                              | Returns                         |
|-----------------|----------------------------------|---------------------------------|
| Read file       | `sandbox.file.read_file(file=path)` | `.data.content` with full text (for text files, e.g., .txt, .md, .tex, etc.) |
| List directory  | `sandbox.file.list_path(path=dir)`  | `.data.entries` list            |
| Download file   | `sandbox.file.download_file(path=path)` | Binary data for streaming (for binary files, e.g., .jpg, .png, .doc, .pptx, etc.) |

## Results

Each task produces a JSON file in the output directory (e.g., `results/task-name.json`) with complete execution details.

**Result Dictionary Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `task_name` | string | Name of the task |
| `instruction` | string | Original task instruction |
| `status` | string | Task status: "success" or "failed" |
| `iterations` | integer | Number of controller iterations |
| `conversation` | array | Full conversation with controller (role/content pairs) |
| `execution_trace` | array | List of actions and their feedback |
| `eval` | object | Evaluation results from `test.py` |
| `execution_time` | float | Total execution time in seconds |
| `docker_port` | integer | Docker port used for this task |
| `client_type` | string | Sandbox client type (unified, browser, etc.) |

## Setup

### Prerequisites

- Python 3.10+
- Docker and Docker Compose (for running sandboxed tasks)
- uv (Python package manager, recommended)

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   uv sync
   ```

3. Set up configuration file:
   - Copy or create a config file in `configs/` directory
   - Update the API key for your LLM provider
   - Configure sandbox settings (docker_port, max_iterations, etc.)

**Example configuration setup:**
```bash
cp configs/default_gpt.json configs/my-config.json
# Edit my-config.json and set your API key
python inference_main.py --config configs/my-config.json --tasks-dir tasks/ --output-dir results/
```

