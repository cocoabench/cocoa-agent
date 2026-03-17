#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
load_openclaw_env

ROOT_DIR="$(openclaw_root_dir)"
PYTHON_BIN="$(openclaw_python)"

OPENCLAW_BASE_URL="${OPENCLAW_BASE_URL:-}"
OPENCLAW_API_KEY="${OPENCLAW_API_KEY:-${OPENAI_API_KEY:-}}"
OPENCLAW_MODEL="${OPENCLAW_MODEL:-gpt-4.1-mini}"
TASK_DIR="${OPENCLAW_TASK_DIR:-${ROOT_DIR}/cocoabench-example-tasks/linear-regime-estimation}"
OUTPUT_DIR=""
RUN_TEST="true"
RUN_NAME="openclaw-direct"
MAX_TOKENS="${OPENCLAW_MAX_TOKENS:-4000}"
TEMPERATURE="${OPENCLAW_TEMPERATURE:-0}"

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
      OPENCLAW_MODEL="$2"
      shift 2
      ;;
    --run-name)
      RUN_NAME="$2"
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
    --skip-test)
      RUN_TEST="false"
      shift
      ;;
    --help|-h)
      cat <<'EOF'
Usage: ./scripts/run-openclaw.sh [options]

Options:
  --task-dir <path>       Task directory containing task.yaml and optional test.py
  --output-dir <path>     Override output directory
  --model <name>          Override model
  --run-name <name>       Prefix output dir with a stable run name
  --max-tokens <n>        Set chat completion max_tokens
  --temperature <value>   Set chat completion temperature
  --skip-test             Skip local test.py execution
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

require_api_key "${OPENCLAW_API_KEY}"
require_task_dir "${TASK_DIR}"

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${ROOT_DIR}/outputs/${RUN_NAME}-$(basename "${TASK_DIR}")-$(date +%Y%m%d-%H%M%S)"
fi

mkdir -p "${OUTPUT_DIR}"

OPENCLAW_BASE_URL="${OPENCLAW_BASE_URL}" \
OPENCLAW_API_KEY="${OPENCLAW_API_KEY}" \
OPENCLAW_MODEL="${OPENCLAW_MODEL}" \
RUN_TEST="${RUN_TEST}" \
MAX_TOKENS="${MAX_TOKENS}" \
TEMPERATURE="${TEMPERATURE}" \
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/direct_openclaw_eval.py" \
  --task-dir "${TASK_DIR}" \
  --output-dir "${OUTPUT_DIR}"

echo "Done. Result files are in: ${OUTPUT_DIR}"
