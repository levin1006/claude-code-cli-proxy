# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview
- This repo is an **operations/config workspace** for a prebuilt CLIProxyAPI binary, not the source code of the proxy itself.
- **Supported platforms**: Windows (PowerShell) and Linux Ubuntu (Bash).
- Binary version in this repo: `CLIProxyAPI_6.8.24_windows_amd64`.
- Main moving parts:
  - `cli-proxy-api.exe` (Windows binary, prebuilt)
  - `cli-proxy-api` (Linux binary, user downloads separately; gitignored)
  - `configs/<provider>/config.yaml` (+ provider credential JSON files)
  - `powershell/cc-proxy.ps1` (Windows orchestration and Claude Code launcher helpers)
  - `bash/cc-proxy.sh` (Linux orchestration and Claude Code launcher helpers)
  - `docs/claude-code-cliproxy-windows-guide.md` (Windows operational background)
  - `docs/claude-code-cliproxy-linux-guide.md` (Linux operational background)
  - `config.yaml` at repo root (bootstrap config used when issuing new auth tokens near the binary)
- References:
  - Official repository: https://github.com/router-for-me/CLIProxyAPI
  - API guide: https://help.router-for.me/

## High-level architecture
1. `cc-<provider>` functions in `powershell/cc-proxy.ps1` (Windows) or `bash/cc-proxy.sh` (Linux) reuse a healthy provider-specific proxy instance when available (start only if needed), then run `claude` with temporary env vars.
2. Provider isolation is done by working directory + `auth-dir: "./"` in each provider config, so each instance only sees credentials in its own folder.
3. Base config files define `port: 8317`; startup rewrites provider base `config.yaml` with provider-specific port and launches the binary with `-config <base-config-file>`.
4. `Invoke-CCProxy` (Windows) / `_cc_proxy_invoke` (Linux) temporarily sets:
   - `ANTHROPIC_BASE_URL`
   - `ANTHROPIC_AUTH_TOKEN=sk-dummy`
   - `ANTHROPIC_DEFAULT_OPUS_MODEL`
   - `ANTHROPIC_DEFAULT_SONNET_MODEL`
   - `ANTHROPIC_DEFAULT_HAIKU_MODEL`
   then restores previous values after `claude` exits.

### Linux-specific architecture notes
- **Process tracking**: PID files at `configs/<provider>/.proxy.pid` (replaces PowerShell in-memory `$script:` state).
- **Port resolution**: `ss -tlnp` (primary) / `lsof` (fallback) — replaces `Get-NetTCPConnection`.
- **Background launch**: `nohup ... &` — replaces `Start-Process -WindowStyle Hidden`.
- **Base dir**: Auto-detected via `BASH_SOURCE[0]` (no hardcoded paths).

### Port model in this repo
Defined in `powershell/cc-proxy.ps1` and `bash/cc-proxy.sh`:
- `claude`: `18417`
- `gemini`: `18418`
- `codex`: `18419`
- `antigravity`: `18420`

## Common commands
> If your shell profile already loads these functions, use commands directly.
> Otherwise, load first from repo root.

### Windows (PowerShell)

#### Load helper functions (one-off shell)
```powershell
. .\powershell\cc-proxy.ps1
```

#### Register helpers in PowerShell profile (recommended first-time setup)
```powershell
. .\powershell\cc-proxy.ps1
Install-CCProxyProfile
```
`Install-CCProxyProfile` updates `$PROFILE` and loads it into the current session immediately.
New PowerShell sessions will auto-load helpers via the profile line.

### Linux (Bash)

#### Load helper functions (one-off shell)
```bash
source bash/cc-proxy.sh
```

#### Register helpers in shell profile (recommended first-time setup)
```bash
source bash/cc-proxy.sh
cc_proxy_install_profile
```
`cc_proxy_install_profile` adds a source line to `~/.bashrc` and `~/.zshrc` (if they exist).
New terminal sessions will auto-load helpers.

### Run Claude Code (both platforms)
```
cc
```
Runs native Claude Code (proxy env vars removed).

### Run Claude Code via provider-specific proxy (both platforms)
```
cc-claude
cc-gemini
cc-codex
cc-ag-claude
cc-ag-gemini
```

### Proxy status and stop (both platforms)
```
cc-proxy-status
cc-proxy-stop
```
`cc-*` commands do not force-stop a healthy running provider proxy; they reuse it and only start if needed.
Use `cc-proxy-stop` when you want an explicit shutdown.

### Health/model checks (single-provider smoke test)
Use `curl` (on Linux) or `curl.exe` (on Windows, not PowerShell `curl` alias):
```
curl -fsS http://127.0.0.1:18417/
curl http://127.0.0.1:18417/v1/models
```
Swap port for other providers (`18418`, `18419`, `18420`).

### Management UI
```text
http://127.0.0.1:<provider-port>/management.html
```

## Editing guidance for future Claude instances
- Prefer editing `powershell/cc-proxy.ps1` (Windows), `bash/cc-proxy.sh` (Linux), and `configs/*/config.yaml`.
- When changing model names or ports, keep both `powershell/cc-proxy.ps1` and `bash/cc-proxy.sh` in sync.
- Treat `configs/*/.config.runtime.yaml` as generated artifacts and keep them untracked.
- Treat `configs/*/.proxy.pid` as Linux runtime state and keep them untracked.
- Use provider base `config.yaml` as dashboard-connected runtime source of truth.
- Do not enforce `remote-management.secret-key`; allow dashboard-managed values.
- For new providers, copy root `config.yaml` as a template and then set provider port.
- Treat `**/main.log` as runtime log output and keep it untracked.
- Keep root `config.yaml` tracked as a bootstrap config for issuing new auth tokens near the binary.
- If changing provider ports, update `CLI_PROXY_PORTS`/`CC_PROXY_PORTS` in both platform scripts; do not rely only on base `config.yaml` ports.
- `routing.strategy` is set to `round-robin` in provider configs.
- Linux binary (`cli-proxy-api`) is gitignored; users download it separately.

## Build / lint / test reality
- No repo-local build/lint/test pipeline was found (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Makefile`, and `README.md` are absent).
- For this repo, practical verification is operational smoke testing via `cc-*`, `cc-proxy-status`, and `/v1/models` checks.

## External instruction files check
- No existing `CLAUDE.md` was found before creation.
- No `.cursorrules` / `.cursor/rules/*` / `.github/copilot-instructions.md` were found in this repo at scan time.