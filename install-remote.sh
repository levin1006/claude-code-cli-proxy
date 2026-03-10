#!/bin/bash
# install-remote.sh — Entry Point (Linux/macOS, Remote/GitHub)
# Delegates to shell/bash/install-remote.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/shell/bash/install-remote.sh" "$@"
