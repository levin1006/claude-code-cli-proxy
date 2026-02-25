#!/usr/bin/env bash
# CLIProxyAPI + Claude Code helpers (Linux/macOS) — thin wrapper
# Delegates all logic to python/cc_proxy.py

if [[ -n "${BASH_VERSION:-}" ]]; then
  CC_PROXY_BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  CC_PROXY_BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

_cc_proxy() { python3 "${CC_PROXY_BASE_DIR}/python/cc_proxy.py" "$@"; }

# Native claude (no proxy) — unsets proxy env in current shell
cc() {
  unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN
  unset ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL
  cc-ag-claude "$@"
}

# Provider entrypoints
cc-ag-claude()  { _cc_proxy run ag-claude -- "$@"; }
cc-claude()     { _cc_proxy run claude    -- "$@"; }
cc-codex()      { _cc_proxy run codex     -- "$@"; }
cc-gemini()     { _cc_proxy run gemini    -- "$@"; }
cc-ag-gemini()  { _cc_proxy run ag-gemini -- "$@"; }

# Management
cc-proxy-start-all()  { _cc_proxy start      all; }
cc-proxy-status()     { _cc_proxy status     "$@"; }
cc-proxy-links()      { _cc_proxy links      "$@"; }
cc-proxy-stop()       { _cc_proxy stop       "$@"; }
cc-proxy-auth()       { _cc_proxy auth       "$@"; }
cc-proxy-set-secret() { _cc_proxy set-secret "$@"; }
cc_proxy_install_profile() { _cc_proxy install-profile; }

# Profile hint on first source
_cc_proxy_show_profile_hint() {
  local src_line="source \"${CC_PROXY_BASE_DIR}/bash/cc-proxy.sh\""
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$rc" ]] && grep -qF "$src_line" "$rc" 2>/dev/null && return
  done
  _cc_proxy install-profile --hint-only
}
_cc_proxy_show_profile_hint
