# Sync Plans to Obsidian

Sync `docs/plans/` files to the Obsidian vault at `~/Code/Personal/obsidian-vault/Plans/`.

Adds YAML frontmatter (project, source, synced, status, tags) and auto commits + pushes to GitHub.

## Steps

1. Run the `sync-plans` shell function with any arguments passed by the user:

```bash
sync-plans $ARGUMENTS
```

2. Report which plans were synced to the user.
