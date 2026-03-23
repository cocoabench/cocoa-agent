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
- `test.py`
- `result.json`
- `eval.json` if testing is enabled
- `agent-response.json`
- `session-trace.jsonl`
- `runner-summary.json`

## Notes

- `timeout-seconds` is enforced through `openclaw agent --timeout`.
- `max-steps` is currently recorded as metadata only.
- The single-task runner records both the requested model and the resolved provider/model name in `result.json`.
- Batch outputs under `outputs/` are gitignored and should not be committed.
