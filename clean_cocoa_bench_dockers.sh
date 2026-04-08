#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOVE_IMAGES=false
REMOVE_NETWORKS=false
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: clean_cocoa_bench_dockers.sh [--images] [--networks] [--dry-run]

Clean CocoaBench task docker resources created by task docker-compose files.

Options:
  --images   Also remove task images matching task-*:latest
  --networks Also remove task compose networks matching <task_name>_default
  --dry-run  Print what would be removed without executing
  -h, --help Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --images)
      REMOVE_IMAGES=true
      shift
      ;;
    --networks)
      REMOVE_NETWORKS=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not in PATH." >&2
  exit 1
fi

mapfile -t CONTAINERS < <(
  docker ps -a --format '{{.Names}}' | awk '/^task-.*-container$/ { print $0 }'
)

if [[ ${#CONTAINERS[@]} -eq 0 ]]; then
  echo "No CocoaBench task containers found."
else
  echo "Found ${#CONTAINERS[@]} CocoaBench task container(s):"
  printf '  %s\n' "${CONTAINERS[@]}"

  if [[ "$DRY_RUN" == true ]]; then
    echo "Dry run: would remove the containers above."
  else
    echo "Removing containers..."
    docker rm -f "${CONTAINERS[@]}"
  fi
fi

if [[ "$REMOVE_IMAGES" == true ]]; then
  mapfile -t IMAGES < <(
    docker images --format '{{.Repository}}:{{.Tag}}' | awk '/^task-.*:latest$/ { print $0 }'
  )

  if [[ ${#IMAGES[@]} -eq 0 ]]; then
    echo "No CocoaBench task images found."
  else
    echo "Found ${#IMAGES[@]} CocoaBench task image(s):"
    printf '  %s\n' "${IMAGES[@]}"

    if [[ "$DRY_RUN" == true ]]; then
      echo "Dry run: would remove the images above."
    else
      echo "Removing images..."
      docker rmi -f "${IMAGES[@]}"
    fi
  fi
fi

if [[ "$REMOVE_NETWORKS" == true ]]; then
  mapfile -t TASK_PROJECTS < <(
    python3 - "$ROOT_DIR" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
projects = set()

for compose_file in root.rglob("docker-compose.yaml"):
    parent = compose_file.parent
    if (parent / "task.yaml.enc").exists() or (parent / "task.yaml").exists():
        projects.add(parent.name)

for name in sorted(projects):
    print(name)
PY
  )

  NETWORKS=()
  for project in "${TASK_PROJECTS[@]}"; do
    network_name="${project}_default"
    if docker network inspect "$network_name" >/dev/null 2>&1; then
      NETWORKS+=("$network_name")
    fi
  done

  if [[ ${#NETWORKS[@]} -eq 0 ]]; then
    echo "No CocoaBench task networks found."
  else
    echo "Found ${#NETWORKS[@]} CocoaBench task network(s):"
    printf '  %s\n' "${NETWORKS[@]}"

    if [[ "$DRY_RUN" == true ]]; then
      echo "Dry run: would remove the networks above."
    else
      echo "Removing networks..."
      docker network rm "${NETWORKS[@]}"
    fi
  fi
fi
