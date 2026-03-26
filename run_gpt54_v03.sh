#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

CONFIG_PATH="${CONFIG_PATH:-my-openai-v03.json}"
TASKS_DIR="${TASKS_DIR:-cocoabench-v0.3}"
OUTPUT_DIR="${1:-results/gpt-5-4-v03-full}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set."
  echo "Run: export OPENAI_API_KEY=\"your_api_key\""
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config file not found: $CONFIG_PATH"
  exit 1
fi

if [[ ! -d "$TASKS_DIR" ]]; then
  echo "Tasks directory not found: $TASKS_DIR"
  exit 1
fi

echo "Syncing dependencies..."
uv sync

cmd=(
  uv run python inference_main.py
  --config "$CONFIG_PATH"
  --tasks-dir "$TASKS_DIR"
  --output-dir "$OUTPUT_DIR"
)

echo "Starting CocoaBench run"
echo "  config: $CONFIG_PATH"
echo "  tasks:  $TASKS_DIR"
echo "  output: $OUTPUT_DIR"

if docker ps >/dev/null 2>&1; then
  exec "${cmd[@]}"
fi

if id -nG | tr ' ' '\n' | rg -xq docker; then
  printf -v cmd_str '%q ' "${cmd[@]}"
  exec sg docker -c "cd $(printf '%q' "$ROOT_DIR") && ${cmd_str}"
fi

echo "Docker is not accessible from this shell."
echo "If you already added your user to the docker group, run:"
echo "  newgrp docker"
echo "Then re-run:"
echo "  ./run_gpt54_v03.sh"
exit 1
