#!/bin/bash
set -e

echo "Starting cli-proxy-api installation..."

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

    # Refresh common user-level bin paths for current shell session
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
REMOTE_MODE=0

# Parse optional args: --tag vX.Y.Z --repo owner/name --remote --port-offset N
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            if [[ $# -lt 2 ]]; then
                echo "Error: --tag requires a value"
                exit 1
            fi
            REQUESTED_TAG="$2"
            shift 2
            ;;
        --repo)
            if [[ $# -lt 2 ]]; then
                echo "Error: --repo requires a value"
                exit 1
            fi
            REPO="$2"
            shift 2
            ;;
        --remote)
            REMOTE_MODE=1
            shift
            ;;
        --port-offset)
            if [[ $# -lt 2 ]]; then
                echo "Error: --port-offset requires a value"
                exit 1
            fi
            PORT_OFFSET="$2"
            shift 2
            ;;
        *)
            echo "Error: unknown argument '$1'"
            echo "Usage: install.sh [--tag <tag-or-branch>] [--repo <owner/name>] [--remote] [--port-offset <number>]"
            exit 1
            ;;
    esac
done

if [[ -z "$PORT_OFFSET" && "$REMOTE_MODE" -eq 1 ]]; then
    PORT_OFFSET="10000"
fi

if [[ -n "$PORT_OFFSET" ]]; then
    if ! [[ "$PORT_OFFSET" =~ ^-?[0-9]+$ ]]; then
        echo "Error: --port-offset must be an integer"
        exit 1
    fi
fi

echo "Using repository ref: $REQUESTED_TAG"

INSTALLER_URL="https://raw.githubusercontent.com/${REPO}/${REQUESTED_TAG}/installers/install.py"
TEMP_SCRIPT="/tmp/install_cc_proxy.py"

echo "Downloading core installation script from repository ref..."
curl -fsSL "$INSTALLER_URL" -o "$TEMP_SCRIPT"

echo "Executing core installation script..."
python3 "$TEMP_SCRIPT" --repo "$REPO" --tag "$REQUESTED_TAG"

if [[ -n "$PORT_OFFSET" ]]; then
    OFFSET_LINE="export CC_PROXY_LOCAL_PORT_OFFSET=$PORT_OFFSET"
    export CC_PROXY_LOCAL_PORT_OFFSET="$PORT_OFFSET"
    echo "Configured port offset for this session: $PORT_OFFSET"

    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        if [[ -f "$rc" ]]; then
            if grep -qxF "$OFFSET_LINE" "$rc" 2>/dev/null; then
                echo "Port offset already configured in $rc"
            else
                printf "\n# Added by cli-proxy installer\n%s\n" "$OFFSET_LINE" >> "$rc"
                echo "Saved port offset to $rc"
            fi
        fi
    done
fi

# Cleanup
rm -f "$TEMP_SCRIPT"
