#!/bin/bash
# shell/bash/install-remote.sh — Remote Bootstrap Installer
# Downloads code from GitHub and installs to ~/.cli-proxy/
#
# WARNING: This downloads from the REMOTE main branch.
#          For local installation, use: ./install-local.sh
set -e

echo "Starting cli-proxy-api REMOTE installation..."

# Check requirements
if ! command -v curl &> /dev/null; then
    echo "Error: curl is required for installation."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required for installation."
    exit 1
fi

# Ensure Claude Code is available for cc-* commands
if ! command -v claude &> /dev/null; then
    echo "Claude Code not found. Installing Claude Code..."
    if curl -fsSL https://claude.ai/install.sh | bash; then
        echo "Claude Code installation completed."
    else
        echo "Error: failed to install Claude Code."
        exit 1
    fi
    export PATH="$HOME/.local/bin:$HOME/.claude/bin:$HOME/bin:$PATH"
fi

if ! command -v claude &> /dev/null; then
    echo "Error: 'claude' command is still unavailable after install."
    echo "Please restart your shell and rerun this installer."
    exit 1
fi

REPO="${CC_PROXY_INSTALL_REPO:-levin1006/claude-code-cli-proxy}"
REQUESTED_TAG="${CC_PROXY_INSTALL_TAG:-main}"
PORT_OFFSET=""
SOURCE_MODE=""
LOCAL_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)       REQUESTED_TAG="$2"; shift 2 ;;
        --repo)      REPO="$2"; shift 2 ;;
        --source)    SOURCE_MODE="$2"; shift 2 ;;
        --local-path) LOCAL_PATH="$2"; shift 2 ;;
        --port-offset) PORT_OFFSET="$2"; shift 2 ;;
        *) echo "Error: unknown argument '$1'"; exit 1 ;;
    esac
done

[[ -z "$SOURCE_MODE" ]] && SOURCE_MODE="remote"

INSTALLER_URL="https://raw.githubusercontent.com/${REPO}/${REQUESTED_TAG}/installers/install.py"
TEMP_SCRIPT="/tmp/install_cc_proxy.py"

echo "Using repository ref: $REQUESTED_TAG"
echo "Downloading core installation script..."
curl -fsSL "$INSTALLER_URL" -o "$TEMP_SCRIPT"

PY_ARGS=(--repo "$REPO" --tag "$REQUESTED_TAG" --source "$SOURCE_MODE")
[[ -n "$LOCAL_PATH" ]] && PY_ARGS+=(--local-path "$LOCAL_PATH")
python3 "$TEMP_SCRIPT" "${PY_ARGS[@]}"

rm -f "$TEMP_SCRIPT"

PROXY_SCRIPT="$HOME/.cli-proxy/shell/bash/cc-proxy.sh"
if [ -f "$PROXY_SCRIPT" ]; then
    echo -e "\n\033[0;36mAuto-loading CLIProxyAPI into current session...\033[0m"
    source "$PROXY_SCRIPT"
    echo -e "\033[0;32mDone! You can now use cc, cc-proxy-start-all, etc.\033[0m"
fi
