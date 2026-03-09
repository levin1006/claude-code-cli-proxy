#!/usr/bin/env bash
# CLIProxyAPI + Claude Code helpers (Linux/macOS) — thin wrapper
# Delegates all logic to core/cc_proxy.py

if [[ -n "${BASH_VERSION:-}" ]]; then
  CC_PROXY_BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
else
  CC_PROXY_BASE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
fi

_cc_proxy_guard_repo_run() {
  local installed_base="$HOME/.cli-proxy"
  if [[ "$CC_PROXY_BASE_DIR" != "$installed_base" && "${CC_PROXY_ALLOW_REPO_RUN:-}" != "1" ]]; then
    printf '[cc-proxy] ERROR: repository execution is disabled.\n' >&2
    printf '[cc-proxy] Run installer sync first, then load from ~/.cli-proxy/shell/bash/cc-proxy.sh\n' >&2
    printf '[cc-proxy] (temporary override: export CC_PROXY_ALLOW_REPO_RUN=1)\n' >&2
    return 1
  fi
  return 0
}

_cc_proxy() {
  _cc_proxy_guard_repo_run || return 1
  python3 "${CC_PROXY_BASE_DIR}/core/cc_proxy.py" "$@"
}

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
cc-proxy-status()     { _cc_proxy status        "$@"; }
cc-proxy-check()      { _cc_proxy status --check "$@"; }  # alias → status --check
cc-proxy-quota()      { _cc_proxy status --quota "$@"; }
cc-proxy-short()      { _cc_proxy status -s       "$@"; }  # compact one-line-per-provider
cc-proxy-ui()         { _cc_proxy ui             "$@"; }
cc-proxy-links()      { _cc_proxy links      "$@"; }
cc-proxy-stop()       { _cc_proxy stop       "$@"; }
cc-proxy-auth()        { _cc_proxy auth         "$@"; }
cc-proxy-token-dir()   { _cc_proxy token-dir    "$@"; }
cc-proxy-token-list()  { _cc_proxy token-list   "$@"; }
cc-proxy-token-delete(){ _cc_proxy token-delete "$@"; }
cc-proxy-set-secret()  { _cc_proxy set-secret   "$@"; }
cc-proxy-version()     { _cc_proxy version      "$@"; }
cc-proxy-usage-clear() { _cc_proxy usage-clear  "$@"; }
cc_proxy_install_profile() { _cc_proxy install-profile; }

# Profile hint on first source
_cc_proxy_show_profile_hint() {
  local installed_base="$HOME/.cli-proxy"
  if [[ "$CC_PROXY_BASE_DIR" != "$installed_base" && "${CC_PROXY_ALLOW_REPO_RUN:-}" != "1" ]]; then
    return
  fi

  local src_line="source \"${CC_PROXY_BASE_DIR}/shell/bash/cc-proxy.sh\""
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$rc" ]] && grep -qF "$src_line" "$rc" 2>/dev/null && return
  done
  _cc_proxy install-profile --hint-only
}
_cc_proxy_show_profile_hint
