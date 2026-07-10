# Codex Client Setup v0.1

## Purpose

This document records the local client state required to attach the CognitiveOS read-only MCP server to Codex.

The Windows details below are the original environment record. The active continuation target is now an Intel Mac; use `System/docs/device-handoff-intel-mac-v0.1.md` as the primary setup guide.

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

The current macOS-targeted MCP server configuration is:

```toml
[mcp_servers.cognitiveos]
command = "/bin/bash"
args = ["scripts/run-cognitiveos-mcp.sh"]
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

The platform launchers and Python server entrypoint are present:

- `scripts/run-cognitiveos-mcp.sh`
- `scripts/run-cognitiveos-mcp.ps1`
- `src/cognitiveos/mcp_server.py`

On macOS, run `scripts/bootstrap-macos.sh` first. On Windows, the PowerShell launcher remains available for direct use even though the tracked Codex MCP registration now targets macOS.

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

Remaining manual verification on the Intel Mac:

- run `scripts/bootstrap-macos.sh`
- sign in to Codex if prompted
- open and trust the vault root
- confirm the project-scoped `.codex/config.toml` loads
- confirm the `cognitiveos` MCP server appears with nine read-only tools
- run `list_recent_notes` and `search_notes` from the Codex UI

## Decision

Implementation-level MCP verification is complete. Client-level verification must now be repeated on the Intel Mac after bootstrap and interactive Codex sign-in.
