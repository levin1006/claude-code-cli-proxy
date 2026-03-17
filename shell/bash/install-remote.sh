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
DO_UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)         REQUESTED_TAG="$2"; shift 2 ;;
        --repo)        REPO="$2"; shift 2 ;;
        --source)      SOURCE_MODE="$2"; shift 2 ;;
        --local-path)  LOCAL_PATH="$2"; shift 2 ;;
        --port-offset) PORT_OFFSET="$2"; shift 2 ;;
        --uninstall)   DO_UNINSTALL=true; shift ;;
        *) echo "Error: unknown argument '$1'"; exit 1 ;;
    esac
done

INSTALLER_URL="https://raw.githubusercontent.com/${REPO}/${REQUESTED_TAG}/installers/install.py?v=$(date +%s)"
TEMP_SCRIPT="/tmp/install_cc_proxy.py"

echo "Downloading core installation script..."
curl -fsSL "$INSTALLER_URL" -o "$TEMP_SCRIPT"

if [ "$DO_UNINSTALL" = true ]; then
    python3 "$TEMP_SCRIPT" --uninstall
    echo ""
    read -p "[?] Do you want to restart the shell now to cleanly remove aliases? (y/N) [Default: N]: " confirm
    if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
        echo "Restarting shell..."
        exec "${SHELL:-bash}"
    else
        echo "Run 'exec \$SHELL' or open a new terminal to clean up lingering aliases."
    fi
else
    [[ -z "$SOURCE_MODE" ]] && SOURCE_MODE="remote"
    echo "Using repository ref: $REQUESTED_TAG"
    PY_ARGS=(--repo "$REPO" --tag "$REQUESTED_TAG" --source "$SOURCE_MODE")
    [[ -n "$LOCAL_PATH" ]] && PY_ARGS+=(--local-path "$LOCAL_PATH")
    python3 "$TEMP_SCRIPT" "${PY_ARGS[@]}"
fi

rm -f "$TEMP_SCRIPT"

PROXY_SCRIPT="$HOME/.cli-proxy/shell/bash/cc-proxy.sh"
if [ -f "$PROXY_SCRIPT" ] && [ "$DO_UNINSTALL" = false ]; then
    echo ""
    echo -e "\033[0;32mInstallation complete!\033[0m"
    echo ""
    read -p "[?] Do you want to restart the shell now to apply changes? (y/N) [Default: N]: " confirm < /dev/tty || confirm="N"
    if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
        echo "Restarting shell..."
        exec "${SHELL:-bash}"
    else
        echo -e "\033[0;36mTo activate in this session manually, run:\033[0m"
        echo -e "  \033[1msource \"$PROXY_SCRIPT\"\033[0m"
        echo ""
        echo "New terminals will load helpers automatically."
    fi
fi
