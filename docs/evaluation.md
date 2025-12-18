# Evaluation Guide

The system uses a **host-side evaluation approach** where the `test()` function in `test.py` validates task results.

## How Evaluation Works

The evaluation script runs on the host machine after task completion. The framework:

1. Loads the `test()` function from `test.py` in the task directory
2. Calls `test(result)` with the complete execution result dictionary
3. Expects a dictionary return value with evaluation results

---

## Function Signature

```python
def test(result: dict) -> dict:
    """Evaluate task results after execution.

    Args:
        result: Complete execution result containing:
            - task_result: Agent's answer
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

### Answer Extraction Logic

Most `test.py` scripts follow this pattern:

1. **First**, try to extract the answer from `task_result` (set when agent calls `task_complete` tool)
2. **If not found**, fall back to searching the `conversation` history

This means if you're using your own agent framework, you can simply pass `task_result` with the agent's final answer—no need to include the full conversation.

---

## Return Format

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

---

## Result Dictionary Contents

```python
result = {
    "task_name": "task-name",
    "instruction": "Task instruction...",
    "status": "success",  # or "failed"
    "iterations": 5,
    "task_result": "agent's final answer",  # The most important field for evaluation
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
