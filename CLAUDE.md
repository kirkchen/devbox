# CLAUDE.md

Dotfiles repo managed by Chezmoi. Adapts to macOS, Linux, and DevContainer environments.

## Rules

- ALWAYS edit files in `chezmoi/` directory, NEVER modify dotfiles directly in home directory.
- ALWAYS use `--source="./chezmoi"` flag with chezmoi commands.
- Test with `chezmoi diff` before applying changes.

## Commands

```bash
chezmoi apply --source="./chezmoi"          # Apply dotfiles
chezmoi diff --source="./chezmoi"           # Preview changes (dry run)
chezmoi init --source="./chezmoi" --apply   # Re-init (prompts for name/email/github_token)
chezmoi add ~/.newconfig --source="./chezmoi"  # Add new dotfile
```

## Workflow

1. Edit files in `chezmoi/`
2. `chezmoi diff` to preview
3. `chezmoi apply` to deploy
4. Commit to git
