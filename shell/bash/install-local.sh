#!/bin/bash
# shell/bash/install-local.sh — Local Installation Script
# Copies the current LOCAL repo code into ~/.cli-proxy/
#
# NOTE: For fresh install from GitHub, use: ./install-remote.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_PY="$REPO_ROOT/installers/install.py"

if [[ " $* " == *" --uninstall "* ]] || [[ "$1" == "--uninstall" ]]; then
    echo "[install-local] Uninstalling cli-proxy..."
    python3 "$INSTALL_PY" --uninstall
else
    echo "[install-local] Local installation: repo -> ~/.cli-proxy/"
    cd "$REPO_ROOT"
    python3 "$INSTALL_PY" --source local
fi

if [ $? -ne 0 ]; then
    echo "[install-local] Failed."
    exit 1
fi

echo "[install-local] Done."

# NOTE: Bash runs this script in a subshell, so we cannot auto-source the
# helpers into the caller's shell. The user must run the line below once.
PROXY_SCRIPT="$HOME/.cli-proxy/shell/bash/cc-proxy.sh"
if [ -f "$PROXY_SCRIPT" ]; then
    echo "[install-local] To activate new commands in this shell, run:"
    echo "  source \"$PROXY_SCRIPT\""
fi
