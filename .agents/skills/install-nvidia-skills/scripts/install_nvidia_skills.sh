#!/usr/bin/env bash
# ==============================================================================
# NVIDIA Agent Skills Installer (https://github.com/nvidia/skills)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve the Git repository root (where .git and top-level .agents/ reside)
WORKSPACE_DIR="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${WORKSPACE_DIR}" ]; then
  curr="${SCRIPT_DIR}"
  while [ "${curr}" != "/" ]; do
    if [ -d "${curr}/.git" ] || [ -d "${curr}/.agents" ]; then
      WORKSPACE_DIR="${curr}"
      break
    fi
    curr="$(dirname "${curr}")"
  done
fi
WORKSPACE_DIR="${WORKSPACE_DIR:-${SCRIPT_DIR}/../../../..}"

show_help() {
  echo "NVIDIA Agent Skills Installer (https://github.com/nvidia/skills)"
  echo ""
  echo "Usage:"
  echo "  $0 --skill <name>   Install a specific NVIDIA skill (e.g. accelerated-computing-cudf)"
  echo "  $0 --all            Install the full NVIDIA skills catalog (340+ skills, ~1-2 min)"
  echo "  $0 --list           List all available skills from the upstream repository"
  echo "  $0 --help           Show this help message"
}

case "${1:-}" in
  --skill|-s)
    SKILL_NAME="${2:-}"
    if [ -z "$SKILL_NAME" ]; then
      echo "❌ Error: --skill requires a skill name."
      exit 1
    fi
    echo "📦 Installing NVIDIA skill '${SKILL_NAME}' into ${WORKSPACE_DIR}/.agents/skills/..."
    (cd "${WORKSPACE_DIR}" && npx -y skills add nvidia/skills --skill "${SKILL_NAME}" --copy -y)
    echo "✨ Skill '${SKILL_NAME}' installed successfully."
    ;;
  --all|-a)
    echo "📦 Installing full NVIDIA skills catalog (~340+ skills) into ${WORKSPACE_DIR}/.agents/skills/..."
    (cd "${WORKSPACE_DIR}" && npx -y skills add nvidia/skills --skill '*' --copy -y)
    echo "✨ All NVIDIA skills installed successfully."
    ;;
  --list|-l)
    echo "🔍 Fetching available skills from https://github.com/nvidia/skills..."
    npx -y skills add nvidia/skills --list
    ;;
  *)
    show_help
    ;;
esac
