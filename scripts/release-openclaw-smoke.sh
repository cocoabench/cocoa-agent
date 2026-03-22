#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
load_openclaw_env

ROOT_DIR="$(openclaw_root_dir)"

TASK_DIR="${RELEASE_TASK_DIR:-${ROOT_DIR}/cocoabench-example-tasks/linear-regime-estimation}"
OUTPUT_DIR=""
MODEL_OVERRIDE=""
MAX_TOKENS="${RELEASE_MAX_TOKENS:-4000}"
TEMPERATURE="${RELEASE_TEMPERATURE:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-dir)
      TASK_DIR="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --model)
      MODEL_OVERRIDE="$2"
      shift 2
      ;;
    --max-tokens)
      MAX_TOKENS="$2"
      shift 2
      ;;
    --temperature)
      TEMPERATURE="$2"
      shift 2
      ;;
    --help|-h)
      cat <<'EOF'
Usage: ./scripts/release-openclaw-smoke.sh [options]

Purpose:
  Run one plaintext CocoaBench example task by sending task.yaml directly to OpenClaw
  and then execute the local test.py if present.

Options:
  --task-dir <path>       Override task directory
  --output-dir <path>     Override output directory
  --model <name>          Override model
  --max-tokens <n>        Set chat completion max_tokens
  --temperature <value>   Set chat completion temperature
  -h, --help              Show help
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${ROOT_DIR}/outputs/release-openclaw-smoke-$(basename "${TASK_DIR}")-$(date +%Y%m%d-%H%M%S)"
fi

RUN_ARGS=(
  "--task-dir" "${TASK_DIR}"
  "--output-dir" "${OUTPUT_DIR}"
  "--run-name" "release-openclaw-smoke"
  "--max-tokens" "${MAX_TOKENS}"
  "--temperature" "${TEMPERATURE}"
)

if [[ -n "${MODEL_OVERRIDE}" ]]; then
  RUN_ARGS+=("--model" "${MODEL_OVERRIDE}")
fi

"${ROOT_DIR}/scripts/run-openclaw.sh" "${RUN_ARGS[@]}"

SUMMARY_PATH="${OUTPUT_DIR}/README.md"
MODEL_NAME="${MODEL_OVERRIDE:-${OPENCLAW_MODEL:-gpt-4.1-mini}}"
RUN_DATE="$(date '+%Y-%m-%d %H:%M:%S %Z')"
TASK_NAME="$(basename "${TASK_DIR}")"

cat > "${SUMMARY_PATH}" <<EOF
# OpenClaw Release Smoke Run

This directory contains a direct OpenClaw smoke run with no Docker or CocoaAgent executor.

- Run time: ${RUN_DATE}
- Task: ${TASK_NAME}
- Task dir: ${TASK_DIR}
- Model: ${MODEL_NAME}

## Flow

1. Read plaintext \`task.yaml\`
2. Send the instruction directly to OpenClaw via OpenAI-compatible chat completions
3. Save the assistant output to \`result.json\`
4. Execute local \`test.py\` and save the verdict to \`eval.json\`

## Suggested release framing

Focus on "task.yaml to test.py end-to-end" instead of benchmark completeness.

> OpenClaw can now take plaintext CocoaBench task instructions directly and run local evaluation scripts end to end. We are publishing the direct smoke path first while broader benchmarking is still in progress.
EOF

echo "Release smoke bundle ready: ${OUTPUT_DIR}"
echo "Summary: ${SUMMARY_PATH}"
