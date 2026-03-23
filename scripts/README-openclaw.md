# OpenClaw Script Notes

This repo keeps two OpenClaw evaluation entrypoints:

- `scripts/run-openclaw-agent-task.py`
  Runs one plaintext CocoaBench task through `openclaw agent`, preserves the full session trace, and runs local `test.py` when present.
- `scripts/run-openclaw-batch-v02.py`
  Runs encrypted `cocoabench-v0.2` tasks in batch by decrypting each task into its output directory and then invoking the single-task agent runner.

## Required local setup

OpenClaw should already be configured on the local machine with provider auth profiles. Both runners use the local OpenClaw agent runtime rather than calling `/chat/completions` directly.

## Single-task runner

Typical invocation:

```bash
./scripts/run-openclaw-agent-task.py \
  --task-dir cocoabench-example-tasks/linear-regime-estimation \
  --output-dir outputs/agent-linear-gpt54 \
  --model gpt-5.4 \
  --thinking-mode high \
  --timeout-seconds 1800 \
  --max-steps 50
```

## Batch runner

Typical invocation:

```bash
./scripts/run-openclaw-batch-v02.py \
  --model gpt-5.4 \
  --thinking-mode high
```

Useful options:

- `--task <name>` to run only a specific v0.2 task. Repeatable.
- `--limit <n>` to run only the first N discovered tasks.
- `--rerun-failed` to retry tasks recorded as failed in the existing manifest.
- `--rerun-completed` to rerun tasks already marked completed.
- `--skip-test` to skip local `test.py` evaluation.

The batch runner maintains:

- `manifest.json`
  Per-task status for resume and progress tracking.
- `summary.json`
  Aggregated counts across the current batch run.

Each task subdirectory contains:

- `task.yaml`
  Decrypted task instruction used for this run.
- `test.py`
  Decrypted local evaluator for this task.
- `result.json`
  Standardized run result, including the final answer, conversation trace, session metadata, and summary metrics such as execution time and tool call count.
- `eval.json`
  Output of `test.py`, including pass/fail status and evaluation feedback.
- `agent-response.json`
  Structured JSON returned directly by `openclaw agent --json`.
- `session-trace.jsonl`
  Full OpenClaw session trace copied from the local session store, including model changes, thinking level changes, assistant messages, and tool activity.
- `runner-summary.json`
  Small per-task summary emitted by the batch runner for quick inspection.

## Notes

- `timeout-seconds` is enforced through `openclaw agent --timeout`.
- `max-steps` is currently recorded as metadata only.
- The single-task runner records both the requested model and the resolved provider/model name in `result.json`.
- Batch outputs under `outputs/` are gitignored and should not be committed.
