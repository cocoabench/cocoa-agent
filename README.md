<h1 align="center">
  <img src="assets/logo-icon.svg" alt="CocoaBench" width="40" height="40" align="absmiddle">
  CocoaAgent
</h1>

<p align="center">
  A Framework for Evaluating and Developing Next-Generation Unified Agents
</p>

<p align="center">
  <a href="https://cocoabench.github.io/"><img src="https://img.shields.io/badge/🌐_Website-3E2723?style=flat" alt="Website"></a>
  <a href="https://cocoabench.github.io/blog.html"><img src="https://img.shields.io/badge/📝_Blog-5D4037?style=flat" alt="Blog"></a>
  <a href="https://cocoabench.github.io/leaderboard.html"><img src="https://img.shields.io/badge/🏆_Leaderboard-795548?style=flat" alt="Leaderboard"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/🐍_Python_3.13+-8D6E63?style=flat" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/📄_MIT_License-A1887F?style=flat" alt="License"></a>
</p>

<br>

## What's Inside

- **CocoaBench Dataset** — Benchmark tasks included directly in this repo: `cocoabench-v0.2/` (stable) and `cocoabench-head/` (community contributions, continuously merged)
- **CocoaAgent Framework** — Model-agnostic agent executor that equips agents with general tools (browser, terminal, file operations, code interpreter) via [AIO Sandbox](https://github.com/agent-infra/sandbox)

> [!NOTE]
> `cocoabench-head/` contains community contributions that are continuously merged. For reproducible evaluation, use a stable release like v0.2.

## Prerequisites

- Python 3.13+
- Docker & Docker Compose
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Quick Start

### Option A: Use the Dataset Only (with your own agent)

```bash
# Browse v0.2 tasks (already in repo)
ls cocoabench-v0.2/

# Decrypt tasks (if encrypted)
python decrypt.py --tasks-dir cocoabench-v0.2/
```

> [!NOTE]
> v0.1 is still available as a historical archive: `https://cocoabench.github.io/assets/data/cocoa-bench-v0.1.zip`

**Each task directory contains:**

| File | Purpose |
|------|---------|
| `task.yaml` | Task instruction to give your agent |
| `test.py` | Evaluation script with `test(result)` function |
| `Dockerfile` | Task environment setup |
| `docker-compose.yaml` | Docker config |
| `assets/` | Additional files for the task (optional) |

**Evaluation:** Each `test.py` exports a `test(result)` function. If you're using your own agent, you typically just need to pass `{"task_result": "<agent's final answer>"}`. See [Evaluation](#evaluation) for details.

### Option B: Run with CocoaAgent Framework

```bash
# 1. Install
git clone https://github.com/cocoabench/cocoa-agent.git && cd cocoa-agent
uv sync  # or: pip install -r requirements.txt

# 2. Choose tasks
# See included example tasks: cocoabench-example-tasks/
# Or download full benchmark dataset: follow Option A above

# 3. Configure
cp configs/default_gpt.json configs/my-config.json
# Edit my-config.json: set your API key

# 4. Run with example tasks
python inference_main.py \
  --config configs/my-config.json \
  --tasks-dir cocoabench-example-tasks/ \
  --output-dir results/

# Or run with full v0.2 dataset (decryption is handled automatically):
# python inference_main.py \
#   --config configs/my-config.json \
#   --tasks-dir cocoabench-v0.2/ \
#   --output-dir results/
```

## OpenClaw Scripts

If you want a minimal OpenClaw entrypoint without Docker or the CocoaAgent executor, use the agent-based runner:

```bash
./scripts/run-openclaw-agent-task.py \
  --task-dir cocoabench-example-tasks/linear-regime-estimation \
  --output-dir outputs/agent-linear-gpt54 \
  --model gpt-5.4 \
  --thinking-mode high
```

This path does the following:

1. Reads plaintext `task.yaml`
2. Runs the task through `openclaw agent`
3. Saves the structured agent response to `outputs/.../agent-response.json`
4. Copies the full OpenClaw session trace to `outputs/.../session-trace.jsonl`
5. Writes the standardized task result to `outputs/.../result.json`
6. Runs the local `test.py` and saves the verdict to `outputs/.../eval.json`

For batch evaluation on the encrypted `cocoabench-v0.2` tasks, use:

```bash
./scripts/run-openclaw-batch-v02.py \
  --model gpt-5.4 \
  --thinking-mode high \
  --limit 2
```

This batch runner decrypts each task into its output directory, runs the same agent-based evaluation path, and maintains top-level `manifest.json` and `summary.json` files for resume and aggregation.

Detailed script usage is documented in `scripts/README-openclaw.md`.
### Parallel Inference

To run tasks in parallel across multiple workers (each with its own Docker sandbox port):

```bash
python parallel_inference.py \
  --config <config_path> \
  --tasks-dir cocoabench-v0.4/ \
  --output-dir <results_dir> \
  --workers 8
```

| Arg | Required | Description |
|-----|----------|-------------|
| `--config` | Yes | Model config file path (JSON) |
| `--tasks-dir` | Yes | Directory containing task subdirectories |
| `--output-dir` | Yes | Final output directory for result JSONs |
| `--workers` | No | Number of parallel workers (default: 4) |
| `--base-port` | No | Starting Docker sandbox port (default: 8084), auto-scans for available ports |
| `--model` | No | Override model name from config |
| `--run-all` | No | Run all tasks including previously passed ones. Default: skip passed, rerun failed/missing only |
| `--work-dir` | No | Temp directory for worker configs/logs (default: `.parallel_run`) |

By default, tasks that already have a successful result in `--output-dir` are skipped, so you can rerun the same command to retry only failed/missing tasks. Use `--run-all` to force rerun everything.

**Output:**
- `output-dir/{task_name}.json` — result file per task
- `output-dir/statistics.txt` — pass rate, failure list, and API cost summary
- `work-dir/` — per-session logs and intermediate files for debugging

## Configuration

Edit your config file to customize the agent:

```json
{
  "controller": {
    "type": "llm",
    "args": {
      "model": "gpt-5.2",
      "api_key": "sk-...",
      "base_url": ""
    }
  },
  "sandbox": {
    "docker_port": 8080,
    "max_iterations": 30
  }
}
```

| Key | Description |
|-----|-------------|
| `controller.args.model` | Model name (e.g., `gpt-5.2`) |
| `controller.args.api_key` | Your API key |
| `controller.args.base_url` | Custom endpoint for local models (optional) |
| `sandbox.docker_port` | Port for sandbox container (default: 8080) |
| `sandbox.max_iterations` | Max agent iterations per task (default: 30) |

## Evaluation

Each task includes a `test.py` that runs on the host machine after the agent completes. The framework calls `test(result)` with the full execution result and expects a pass/fail verdict.

```python
def test(result: dict) -> dict:
    """Evaluate task results after execution.

    Args:
        result: Complete execution result containing:
            - task_result: Agent's final answer
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

> [!TIP]
> Most `test.py` scripts first try to extract the answer from `task_result`, then fall back to searching the `conversation` history. If you're using your own agent, you can typically just pass `task_result` with the agent's final answer.

Results are saved to `results/<task-name>.json` when using the CocoaAgent framework.

**Learn more:**

- [Evaluation Guide](docs/evaluation.md) — Complete result dictionary structure and return format
- [Sandbox API Reference](docs/sandbox-api.md) — How to access files and state inside the sandbox container

## Contributing New Tasks

We welcome new benchmark tasks! See [contrib/CONTRIBUTING.md](contrib/CONTRIBUTING.md) for guidelines.

> [!IMPORTANT]
> Please encrypt your task before submitting a PR to keep benchmark data safe from being found by the agent.

## Citation

```bibtex
@misc{cocoabench2025,
  title={CocoaBench: An Evaluation Framework for General Agents with Compositional Cognitive Abilities},
  author={Shibo Hao and Zhining Zhang and Zhiqi Liang and Tianyang Liu and Zilong Wang and others},
  howpublished={Blog post},
  month={December},
  year={2025},
  url={https://cocoabench.github.io/}
}
```
