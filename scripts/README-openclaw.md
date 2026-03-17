# OpenClaw Script Notes

These scripts implement the lightest OpenClaw evaluation path in this repo:

1. Read plaintext `task.yaml`
2. Send the instruction directly to an OpenAI-compatible OpenClaw endpoint
3. Save the raw result locally
4. Run local `test.py` if present

## Files

- `scripts/run-openclaw.sh`
  Runs one task directory end to end.
- `scripts/release-openclaw-smoke.sh`
  Runs the default smoke task for repo/release demos.
- `scripts/direct_openclaw_eval.py`
  Python helper that performs the API call and local evaluation.
- `scripts/lib/common.sh`
  Shared env and input validation helpers.

## Environment Variables

Required:

- `OPENCLAW_BASE_URL`
- `OPENCLAW_API_KEY` or `OPENAI_API_KEY`
- `OPENCLAW_MODEL`

Optional:

- `OPENCLAW_TASK_DIR`
- `OPENCLAW_MAX_TOKENS`
- `OPENCLAW_TEMPERATURE`
- `RELEASE_TASK_DIR`
- `RELEASE_MAX_TOKENS`
- `RELEASE_TEMPERATURE`

## Recommended Usage

Run one task directly:

```bash
./scripts/run-openclaw.sh \
  --task-dir cocoabench-example-tasks/linear-regime-estimation
```

Run the release smoke path:

```bash
./scripts/release-openclaw-smoke.sh
```

## Outputs

Each run writes into `outputs/<run-name>-<task>-<timestamp>/`.

Expected files:

- `result.json`
- `eval.json` if `test.py` exists and test execution is enabled
- `README.md` for release smoke runs

## How To Configure

A minimal `.env` looks like this:

```bash
OPENCLAW_BASE_URL="https://your-openclaw-endpoint/v1"
OPENCLAW_API_KEY="your-key"
OPENCLAW_MODEL="your-model-name"
```

You can also provide the key via `OPENAI_API_KEY`.

## How To Run

Run a single task:

```bash
./scripts/run-openclaw.sh \
  --task-dir cocoabench-example-tasks/linear-regime-estimation
```

Run the default smoke task:

```bash
./scripts/release-openclaw-smoke.sh
```

## How To Test

If the task directory contains `test.py`, the scripts run it automatically and write the verdict to `eval.json`.

If you only want the model response and want to skip local evaluation:

```bash
./scripts/run-openclaw.sh \
  --task-dir cocoabench-example-tasks/linear-regime-estimation \
  --skip-test
```
