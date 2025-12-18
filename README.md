<h1 align="center">
  <img src="assets/logo-icon.svg" alt="CocoaBench" width="40" height="40" align="absmiddle">
  CocoaAgent
</h1>

<p align="center">
  An Evaluation Framework for General Agents with Compositional Cognitive Abilities
</p>

<p align="center">
  <a href="https://cocoabench.github.io/">
    <img src="https://img.shields.io/badge/🌐_Website-3E2723?style=flat" alt="Website">
  </a>
  &nbsp;
  <a href="https://cocoabench.github.io/blog.html">
    <img src="https://img.shields.io/badge/📝_Blog-2ECC71?style=flat" alt="Blog">
  </a>
  &nbsp;
  <a href="https://cocoabench.github.io/leaderboard.html">
    <img src="https://img.shields.io/badge/🏆_Leaderboard-F39C12?style=flat" alt="Leaderboard">
  </a>
  &nbsp;
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/🐍_Python_3.13+-3776AB?style=flat" alt="Python">
  </a>
  &nbsp;
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/📄_MIT_License-9E9E9E?style=flat" alt="License">
  </a>
</p>

<br>

## 📦 What's Inside

- **CocoaBench Dataset** — Benchmark tasks designed around cognitive abilities (perception, reasoning, memory) rather than specific tools
- **CocoaAgent Framework** — Model-agnostic agent executor that equips agents with general tools (browser, terminal, file operations, code interpreter) via [AIO Sandbox](https://github.com/agent-infra/sandbox)

## 🛠️ Prerequisites

- Python 3.13+
- Docker & Docker Compose
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## ☕ Why CocoaBench?

Current agent benchmarks often reward domain-specific workflows rather than general cognitive abilities. CocoaBench focuses on:

- **Perception**: How agents extract and preprocess information from diverse sources (websites, files, images)
- **Reasoning**: Multi-step planning with deductive, inductive, and abductive inference
- **Memory**: Managing working memory and procedural skills across long trajectories
- **Composition**: How agents combine these abilities to solve complex, open-ended tasks

Tasks are human-understandable and automatically evaluated, but designed to challenge agents that can adapt across domains rather than overfit to specific environments.

## 🚀 Quick Start

### Option A: Use the Dataset Only (with your own agent)

```bash
# 1. Download and decrypt
curl -LO https://cocoabench.github.io/assets/data/cocoa-bench-v0.1.zip
unzip cocoa-bench-v0.1.zip && rm cocoa-bench-v0.1.zip
python decrypt.py

# 2. Browse tasks
ls cocoa-bench-v0.1/
```

**Each task directory contains:**

| File | Purpose |
|------|---------|
| `task.yaml` | Task instruction to give your agent |
| `test.py` | Evaluation script with `test(result)` function |
| `Dockerfile` | Task environment setup |
| `docker-compose.yaml` | Docker config |
| `assets/` | Additional files for the task (optional) |

**Evaluation:** Each `test.py` exports a `test(result)` function. If you're using your own agent, you typically just need to pass `{"task_result": "<agent's final answer>"}`. See [Evaluation](#-evaluation) for details.

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

# Or run with full dataset (after downloading):
# python inference_main.py \
#   --config configs/my-config.json \
#   --tasks-dir cocoa-bench-v0.1/ \
#   --output-dir results/
```

## ⚙️ Configuration


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

## ⚖️ Evaluation

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

- [📖 Evaluation Guide](docs/evaluation.md) — Complete result dictionary structure and return format
- [🔌 Sandbox API Reference](docs/sandbox-api.md) — How to access files and state inside the sandbox container

## 🤝 Contributing New Tasks

We welcome new benchmark tasks! See [contrib/CONTRIBUTING.md](contrib/CONTRIBUTING.md) for guidelines.

> [!IMPORTANT]
> Please encrypt your task before submitting a PR to keep benchmark data safe.

## 📄 Citation

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
