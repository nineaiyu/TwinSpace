#!/usr/bin/env bash
# ==============================================================================
# TwinSpace GUI Local Runner Script
# Launches the BeeWare (Toga) GUI application for local development & testing.
# ==============================================================================

set -e

# Resolve project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

# Choose Python executable: project venv, conda TwinSpace env, then system Python
PYTHON_CMD="python"
if [ -x "${PROJECT_ROOT}/.venv/bin/python" ]; then
    PYTHON_CMD="${PROJECT_ROOT}/.venv/bin/python"
elif [ -x "/opt/homebrew/anaconda3/envs/TwinSpace/bin/python" ]; then
    PYTHON_CMD="/opt/homebrew/anaconda3/envs/TwinSpace/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
fi

export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}:${PYTHONPATH:-}"

echo "=================================================="
echo "🚀 Starting TwinSpace GUI (BeeWare / Toga)"
echo "📁 Root:   ${PROJECT_ROOT}"
echo "🐍 Python: $("${PYTHON_CMD}" --version 2>&1)"
echo "=================================================="

MODE="${1:-direct}"

case "${MODE}" in
    --dev|-d|dev)
        echo "🔧 Running in Briefcase Dev mode (briefcase dev)..."
        exec "${PYTHON_CMD}" -m briefcase dev
        ;;
    --build|-b|build)
        echo "📦 Building macOS Native App (briefcase build macOS)..."
        exec "${PYTHON_CMD}" -m briefcase build macOS
        ;;
    --dmg|--package|-p|package)
        echo "📦 Packaging macOS DMG Installer (scripts/build_gui.sh)..."
        shift || true
        exec "${SCRIPT_DIR}/build_gui.sh" "$@"
        ;;
    --app|-a|run)
        echo "▶️ Running built macOS App (briefcase run macOS)..."
        exec "${PYTHON_CMD}" -m briefcase run macOS
        ;;
    --help|-h|help)
        echo "Usage: bash scripts/run_gui.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  (no args)       Launch GUI directly with Python (fastest for development)"
        echo "  --dev, -d       Launch via 'briefcase dev'"
        echo "  --build, -b     Build macOS Native Application bundle"
        echo "  --dmg, -p       Package into macOS .dmg installer (scripts/build_gui.sh)"
        echo "  --app, -a       Run the built macOS App via 'briefcase run macOS'"
        echo "  --help, -h      Show this help message"
        exit 0
        ;;
    *)
        echo "🖥️ Launching GUI application..."
        exec "${PYTHON_CMD}" -m twinspace.gui
        ;;
esac
