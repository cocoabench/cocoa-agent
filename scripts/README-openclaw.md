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

## What To Share Publicly

Reasonable to share:

- The environment variable names
- Example commands
- The fact that OpenClaw uses an OpenAI-compatible API
- The default smoke task name

Do not share:

- Real API keys
- Private endpoint URLs
- Internal model aliases if they are not meant to be public
- Any configuration that could be mistaken for an official benchmark setting

## Suggested Public Framing

For repo release or Twitter, describe this as a direct smoke path:

`task.yaml -> OpenClaw response -> local test.py`

That is accurate and avoids overstating benchmark coverage.
