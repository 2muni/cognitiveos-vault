# Git Versioning Policy

This repository versions the PKM system, not private knowledge content.

## Tracked By Git

- `README.md`
- `AGENTS.md`
- `.codex/`
- `.gitignore`
- `System/docs/`
- `System/templates/`
- folder placeholders such as `.gitkeep`

## Excluded From Git

- personal notes in `00_Inbox/`
- concept notes in `01_Concepts/`
- entity notes in `02_Entities/`
- project notes in `03_Projects/`
- reference notes in `04_References/`
- journal entries in `05_Journal/`
- maps in `06_Maps/`
- attachments in `Assets/`
- Obsidian workspace state, cache, plugin private data
- generated indexes, embeddings, vector stores, graph stores, local databases, logs, and secrets

## Rationale

The repository should be safe to publish or synchronize as infrastructure. Private Markdown records remain local and should be backed up through Obsidian Sync, iCloud, local backup, or encrypted backup.

## If Personal Notes Were Already Added

Run this once from the vault root in an environment where Git is available:

```powershell
git rm -r --cached 00_Inbox 01_Concepts 02_Entities 03_Projects 04_References 05_Journal 06_Maps Assets
git add .gitignore AGENTS.md .codex System README.md
git status --short
```

This removes personal content from Git tracking without deleting files from disk.
