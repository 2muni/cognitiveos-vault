# Codex Client Setup v0.1

## Purpose

This document records the local client state required to attach the CognitiveOS read-only MCP server to Codex.

## Current Environment

Checked on 2026-07-10.

Result:

- VS Code is installed.
  - Version: `1.128.0`
- Codex VS Code extension is installed.
  - Extension ID: `openai.chatgpt`
  - Version: `26.707.31428`
- `node` was not found on the current PowerShell PATH.
- `npm` was not found on the current PowerShell PATH.
- `winget` was not found on the current PowerShell PATH.
- The only `codex` executable currently visible on PATH is the WindowsApps packaged app resource:
  - `C:\Program Files\WindowsApps\OpenAI.Codex_26.623.19656.0_x64__2p2nqsd0c76g0\app\resources\codex.exe`
- Direct CLI use of the WindowsApps packaged `codex.exe` is blocked by Windows access control.

## Existing CognitiveOS MCP Configuration

The project already contains a project-scoped Codex configuration at `.codex/config.toml`.

The configured MCP server is:

```toml
[mcp_servers.cognitiveos]
command = "powershell"
args = ["-ExecutionPolicy", "Bypass", "-File", "scripts/run-cognitiveos-mcp.ps1"]
cwd = "."
startup_timeout_sec = 20
tool_timeout_sec = 60
enabled = true
enabled_tools = [
  "search_notes",
  "read_note",
  "list_recent_notes",
  "get_backlinks",
  "get_related_notes",
  "suggest_links",
  "summarize_source",
  "propose_moc",
  "build_context_pack",
]
default_tools_approval_mode = "prompt"
```

The MCP server script and Python server entrypoint are present:

- `scripts/run-cognitiveos-mcp.ps1`
- `src/cognitiveos/mcp_server.py`

## Official Setup Path

OpenAI Codex MCP configuration is stored in `config.toml`. The CLI and IDE extension share this configuration, and project-scoped `.codex/config.toml` is supported for trusted projects.

For this vault, the cleanest path is:

1. Install or enable the Codex IDE extension in VS Code.
2. Open this vault folder in VS Code.
3. Trust the workspace if prompted.
4. Confirm the extension reads the project-scoped `.codex/config.toml`.
5. Verify that the `cognitiveos` MCP server appears in the Codex MCP/tool settings.
6. Run a read-only tool call such as `search_notes` or `list_recent_notes`.

Alternative path:

1. Install a standalone Codex CLI that can run from PowerShell outside the WindowsApps package boundary.
2. Run `codex` from this vault root.
3. Use the Codex MCP view or command surface to confirm that `cognitiveos` loads from `.codex/config.toml`.
4. Run a read-only MCP tool call.

## Recommendation

Use the VS Code Codex extension first.

Rationale:

- VS Code is already installed and available on PATH.
- CognitiveOS already has project-scoped MCP config.
- No Node/npm installation is required for the existing Python-based MCP server.
- This keeps the setup close to the target workflow: editing Obsidian Markdown and calling read-only PKM tools from the editor.

Use the standalone CLI path only if:

- the VS Code extension is unavailable for the account or workspace,
- command-line automation becomes the primary workflow,
- or MCP debugging requires CLI-specific commands.

## Verification Checklist

After installing the client:

1. Open the vault root:

```powershell
code "C:\Users\2muni\iCloudDrive\iCloud~md~obsidian\Obsidian Vault"
```

2. Confirm this file exists:

```powershell
Test-Path ".codex\config.toml"
```

3. Confirm the MCP server can start directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-cognitiveos-mcp.ps1
```

This command starts a stdio server and waits for protocol input, so no normal prompt-style output is expected.

4. In Codex, verify that the `cognitiveos` server exposes these read-only tools:

- `search_notes`
- `read_note`
- `list_recent_notes`
- `get_backlinks`
- `get_related_notes`
- `suggest_links`
- `summarize_source`
- `propose_moc`
- `build_context_pack`

## Completed Verification

Completed on 2026-07-10:

- VS Code extension installation succeeded:
  - `openai.chatgpt@26.707.31428`
- The CognitiveOS MCP server starts through `scripts/run-cognitiveos-mcp.ps1`.
- The MCP server responds to `initialize`.
- The MCP server responds to `tools/list`.
- The advertised tools are read-only.

Remaining manual verification:

- Open VS Code after extension installation.
- Sign in to Codex if prompted.
- Open the Codex sidebar.
- Confirm the extension loads the project-scoped `.codex/config.toml`.
- Confirm the `cognitiveos` MCP server appears in the Codex UI.
- Run a read-only call from the Codex UI, preferably `list_recent_notes` or `search_notes`.

## Decision

Client-level MCP verification is no longer blocked by extension installation. The remaining step is interactive VS Code/Codex sign-in and UI-level MCP discovery.
