#!/bin/bash
# install.sh — Linux thin wrapper for the cli-proxy installer.
#
# Usage (recommended — remote):
#   curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.sh | bash
#   curl -fsSL <URL>/install.sh | bash -- --port-offset 10000
#
# Usage (local, from repo root):
#   bash installers/install.sh [--source local] [--port-offset 10000] [...]
#
# All arguments are forwarded to installers/install.py unchanged.
# All installation logic (Claude Code install, port-offset, etc.) lives in install.py.

set -e

# ── 1. Check requirements ─────────────────────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required for installation."
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo "Error: curl is required to download install.py."
    exit 1
fi

# ── 2. Resolve install.py (local tree or remote download) ─────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
LOCAL_INSTALL="$SCRIPT_DIR/install.py"
TEMP_INSTALL="/tmp/install_cc_proxy_$$.py"

REPO="${CC_PROXY_INSTALL_REPO:-levin1006/claude-code-cli-proxy}"
TAG="${CC_PROXY_INSTALL_TAG:-main}"

if [ -f "$LOCAL_INSTALL" ]; then
    INSTALL_SCRIPT="$LOCAL_INSTALL"
    echo "Using local install.py: $INSTALL_SCRIPT"
    PY_ARGS=("$@")
else
    # Running via curl | bash — download install.py
    INSTALLER_URL="https://raw.githubusercontent.com/${REPO}/${TAG}/installers/install.py"
    echo "Downloading install.py from $INSTALLER_URL ..."
    curl -fsSL "$INSTALLER_URL" -o "$TEMP_INSTALL"
    INSTALL_SCRIPT="$TEMP_INSTALL"
    # Inject --source remote unless caller already specified --source
    if [[ " $* " != *" --source "* ]]; then
        PY_ARGS=("--repo" "$REPO" --tag "$TAG" "--source" "remote" "$@")
    else
        PY_ARGS=("--repo" "$REPO" --tag "$TAG" "$@")
    fi
fi

# ── 3. Run install.py ─────────────────────────────────────────────────────────
python3 "$INSTALL_SCRIPT" "${PY_ARGS[@]}"
EXIT_CODE=$?

# Cleanup temp file if used
if [ "$INSTALL_SCRIPT" = "$TEMP_INSTALL" ] && [ -f "$TEMP_INSTALL" ]; then
    rm -f "$TEMP_INSTALL"
fi

exit $EXIT_CODE
