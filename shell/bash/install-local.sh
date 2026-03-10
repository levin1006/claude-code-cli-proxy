#!/bin/bash
# shell/bash/install-local.sh — Local Installation Script
# Copies the current LOCAL repo code into ~/.cli-proxy/
#
# NOTE: For fresh install from GitHub, use: ./install-remote.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_PY="$REPO_ROOT/installers/install.py"

echo "[install-local] Local installation: repo -> ~/.cli-proxy/"
cd "$REPO_ROOT"
python3 "$INSTALL_PY" --source local

if [ $? -ne 0 ]; then
    echo "[install-local] Failed."
    exit 1
fi

echo "[install-local] Done."

PROXY_SCRIPT="$HOME/.cli-proxy/shell/bash/cc-proxy.sh"
if [ -f "$PROXY_SCRIPT" ]; then
    echo "Run: source $PROXY_SCRIPT   (to activate in current shell)"
fi
