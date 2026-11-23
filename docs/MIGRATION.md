# Existing-project migration

`alpa migrate` replaces a project's legacy Claude control plane without deleting product work.

## Preserved

- Game code, assets, scenes, tests, Git history, uncommitted work and product documentation.
- Project-specific `.claude/agents` and `.claude/rules`, restored as Alpa Studio extensions.
- Existing Unity runtime/package dependencies. Package migration is a separate, tested activity.

## Replaced

- Project `.claude/settings.json`, legacy plugin enablement and generic framework agents/skills/hooks.
- Current `/alpa-studio:next-task` workflow references become `/next-task` in `CLAUDE.md`, `docs/BACKLOG.md`, and `scripts/run-backlog.sh`. Historical progress is not rewritten.
- Unattended permission bypass is rejected.

## Recovery

Before replacement, `.claude`, `CLAUDE.md`, `docs/BACKLOG.md`, and `scripts/run-backlog.sh` are copied or moved into `.alpa-studio/migration-backups/<timestamp>/`. `.alpa-studio/migration.json` records Git HEAD, dirty-entry count, preserved dependencies, project extensions, approval and baseline-task IDs.

Review first:

```sh
./bin/alpa migrate --project /absolute/UnityProject --profile example
```

Apply only after the plan is accepted:

```sh
./bin/alpa migrate --project /absolute/UnityProject --profile example --apply --replace-claude
```

# Upgrading to 0.3.0 (`alpa upgrade`)

For projects already installed with an older framework version (for example 0.2.x).

```sh
./bin/alpa upgrade --project /absolute/UnityProject                       # Phase A, read-only
./bin/alpa upgrade --project /absolute/UnityProject --apply               # Phase B
./bin/alpa upgrade --project /absolute/UnityProject --rollback .alpa-studio/upgrade-backups/<DIR>
```

- **Phase A (dry-run/report, read-only):** reports from/to version, files to add, settings to merge, preserved local conflicts and active-session blockers. The result is `MIGRATION_READY` when nothing but a live session blocks it.
- **Phase B (apply, only when no active session):** refuses while a Claude process, runner lock or recent hook event is found. Otherwise it makes a verified SHA-256 backup, merges `settings.json`, adds the `execution` config, then validates that task and approval history are unchanged. Any failed validation triggers automatic rollback.
- **Phase C (post-checks):** `scripts/alpa status` and `scripts/alpa run --dry-run`.

Backups in `.alpa-studio/upgrade-backups/` are never deleted. A project that keeps a checkbox backlog in `docs/BACKLOG.md` can use `--task-source backlog`.

# Upgrading from AI Game Studio 0.3.x to Alpa Studio 0.4.0

0.4.0 renames the framework. Old installs keep working:

| 0.3.x | 0.4.0 |
|---|---|
| `bin/ags`, `scripts/ags` | `bin/alpa`, `scripts/alpa` (`ags` still works and prints one deprecation line) |
| `.ai-game-studio/` | `.alpa-studio/` |
| `.claude/rules/ai-game-studio.md` | `.claude/rules/alpa-studio.md` |
| `AGS_*` environment variables | `ALPA_*` (the `AGS_*` names are still read as a fallback) |

- `alpa upgrade --project <P>` (dry-run) lists the layout renames; `--apply` takes a verified backup
  first, then moves the state dir and the renamed files and rewrites the manifest keys. Task, approval
  and handoff history move with the state dir unchanged.
- Any project command (`alpa status`, `alpa run`, ...) on a legacy layout migrates it automatically
  and says so on stderr.
- **Rollback caveat:** `alpa upgrade --rollback <backup>` restores the legacy files and
  `.ai-game-studio/`, but it does not delete `.alpa-studio/`. While `.alpa-studio/` exists, the legacy
  layout is not migrated again. The backup itself lives in `.alpa-studio/upgrade-backups/`, so copy it
  elsewhere before you remove `.alpa-studio/` to retry the migration.
- The default continue phrases are `start` and `continue`; set `execution.continue_phrases` in
  `.alpa-studio/config.json` to use your own (for example a phrase in your language).
