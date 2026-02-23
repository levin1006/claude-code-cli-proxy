# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview
- This repo is an **operations/config workspace** for a prebuilt `cli-proxy-api.exe` on Windows, not the source code of the proxy itself.
- Binary version in this repo: `CLIProxyAPI_6.8.24_windows_amd64`.
- Main moving parts:
  - `cli-proxy-api.exe` (prebuilt binary)
  - `configs/<provider>/config.yaml` (+ provider credential JSON files)
  - `powershell/cc-proxy.ps1` (orchestration and Claude Code launcher helpers)
  - `docs/claude-code-cliproxy-windows-guide.md` (operational background)
  - `config.yaml` at repo root (bootstrap config used when issuing new auth tokens near `cli-proxy-api.exe`)
- References:
  - Official repository: https://github.com/router-for-me/CLIProxyAPI
  - API guide: https://help.router-for.me/

## High-level architecture
1. `cc-<provider>` functions in `powershell/cc-proxy.ps1` start a provider-specific proxy instance and then run `claude` with temporary env vars.
2. Provider isolation is done by working directory + `auth-dir: "./"` in each provider config, so each instance only sees credentials in its own folder.
3. Base config files define `port: 8317`; startup rewrites provider base `config.yaml` with provider-specific port and launches `cli-proxy-api.exe -config <base-config-file>`.
4. `Invoke-CCProxy` temporarily sets:
   - `ANTHROPIC_BASE_URL`
   - `ANTHROPIC_AUTH_TOKEN=sk-dummy`
   - `ANTHROPIC_DEFAULT_OPUS_MODEL`
   - `ANTHROPIC_DEFAULT_SONNET_MODEL`
   - `ANTHROPIC_DEFAULT_HAIKU_MODEL`
   then restores previous values after `claude` exits.

### Port model in this repo
Defined in `powershell/cc-proxy.ps1`:
- `claude`: `18417`
- `gemini`: `18418`
- `codex`: `18419`
- `antigravity`: `18420`

## Common commands
> If your PowerShell profile already loads these functions, use commands directly.
> Otherwise, dot-source first from repo root.

### Load helper functions (one-off shell)
```powershell
. .\powershell\cc-proxy.ps1
```

### Register helpers in PowerShell profile (recommended first-time setup)
```powershell
. .\powershell\cc-proxy.ps1
Install-CCProxyProfile
```
`Install-CCProxyProfile` updates `$PROFILE` and loads it into the current session immediately.
New PowerShell sessions will auto-load helpers via the profile line.

### Run Claude Code
```powershell
cc
```
Runs native Claude Code (proxy env vars removed).

### Run Claude Code via provider-specific proxy
```powershell
cc-claude
cc-gemini
cc-codex
cc-ag-claude
cc-ag-gemini
```

### Proxy status and stop
```powershell
cc-proxy-status
cc-proxy-stop
```

### Health/model checks (single-provider smoke test)
Use `curl.exe` (not PowerShell `curl` alias):
```powershell
curl.exe -fsS http://127.0.0.1:18417/
curl.exe http://127.0.0.1:18417/v1/models
```
Swap port for other providers (`18418`, `18419`, `18420`).

### Management UI
```text
http://127.0.0.1:<provider-port>/management.html
```

## Editing guidance for future Claude instances
- Prefer editing `powershell/cc-proxy.ps1` and `configs/*/config.yaml`.
- Treat `configs/*/.config.runtime.yaml` as generated artifacts and keep them untracked.
- Use provider base `config.yaml` as dashboard-connected runtime source of truth.
- Do not enforce `remote-management.secret-key`; allow dashboard-managed values.
- For new providers, copy root `config.yaml` as a template and then set provider port.
- Treat `**/main.log` as runtime log output and keep it untracked.
- Keep root `config.yaml` tracked as a bootstrap config for issuing new auth tokens near `cli-proxy-api.exe`.
- If changing provider ports, update `CLI_PROXY_PORTS` in `powershell/cc-proxy.ps1`; do not rely only on base `config.yaml` ports.
- `routing.strategy` is set to `round-robin` in provider configs.

## Build / lint / test reality
- No repo-local build/lint/test pipeline was found (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Makefile`, and `README.md` are absent).
- For this repo, practical verification is operational smoke testing via `cc-*`, `cc-proxy-status`, and `/v1/models` checks.

## External instruction files check
- No existing `CLAUDE.md` was found before creation.
- No `.cursorrules` / `.cursor/rules/*` / `.github/copilot-instructions.md` were found in this repo at scan time.