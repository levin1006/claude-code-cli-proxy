#!/bin/bash
# install-local.sh — Entry Point (Linux/macOS, Local)
# Delegates to shell/bash/install-local.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/shell/bash/install-local.sh" "$@"
