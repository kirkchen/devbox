# CLAUDE.md

Dotfiles repo managed by Chezmoi. Adapts to macOS, Linux, and DevContainer environments.

## Rules

- ALWAYS edit files in `chezmoi/` directory, NEVER modify dotfiles directly in home directory.
- ALWAYS use `--source="./chezmoi"` flag with chezmoi commands.
- Test with `chezmoi diff` before applying changes.
- NEVER add or commit `docs/superpowers/`; it contains local planning artifacts.

## Commands

```bash
chezmoi apply --source="./chezmoi"          # Apply dotfiles
chezmoi diff --source="./chezmoi"           # Preview changes (dry run)
chezmoi init --source="./chezmoi" --apply   # Re-init (prompts for name/email/github_token)
chezmoi add ~/.newconfig --source="./chezmoi"  # Add new dotfile
```

## Zsh Tests

```bash
zsh tests/zsh/nvm_lazy_load_test.zsh
zsh -df tests/zsh/kubernetes_test.zsh

zsh -n chezmoi/private_dot_config/zsh/tools.zsh
zsh -n chezmoi/private_dot_config/zsh/kubernetes.zsh
zsh -n chezmoi/private_dot_config/zsh/oh-my-zsh.zsh
zsh -n chezmoi/private_dot_config/zsh/vault.zsh
bash -n chezmoi/dot_local/bin/executable_vault-token-helper
git diff --check
```

## Workflow

1. Edit files in `chezmoi/`
2. Run the relevant tests
3. `chezmoi diff` to preview
4. `chezmoi apply` to deploy
5. Commit only the intended source and documentation files
