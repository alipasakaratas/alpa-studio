# EPIC-001 — Autonomous Context & Session Management (framework 0.3.2)

Handoff file for this epic. New sessions read this instead of chat history.

## Decisions (2026-11-12)

- Default execution policy = **auto**: `scripts/studio-start.sh` launches `alpa run`, an external
  orchestrator that runs one fresh `claude -p` process per task until no eligible work remains,
  a limit is hit, the owner pauses, a fatal error occurs or all remaining work needs approval.
  Manual `/clear` → a continue phrase is a fallback only.
- One Context & Session Manager module (`src/alpa_studio/session.py`) extends the existing
  `tasks.json` ledger, `runner_once`, `studio_hook.py`, approvals and checkpoints. No parallel system.
- Task sources: `ledger` (`.alpa-studio/tasks.json`, canonical) and `backlog`
  (`docs/BACKLOG.md`, a pilot project's existing line format, read-only for the orchestrator; it
  supersedes `scripts/run-backlog.sh` without deleting it).
- Completion is decided by the orchestrator from a recorded result (`alpa task finish`), never from
  Claude's exit code or claims. Missing evidence → not DONE.
- Never `bypassPermissions`. Default runner permission mode is `acceptEdits`; the runner grants the
  local and web tools needed to complete a task. Deterministic hooks protect credentials, paid
  services, publishing and destructive commands; Git writes are limited to `alpa/<task-id>`.
- The two pilot projects have live interactive sessions → migration is staged (`MIGRATION_READY`)
  and dry-run only; apply is blocked by active-session detection.
- The 0.3.0 review-package note is preserved as historical evidence; it is not an independent
  security certification of 0.3.1.

## Tasks

| ID | Task | Status |
|----|------|--------|
| T1 | Inspect an earlier pilot, the framework and two private pilot projects (read-only) | done |
| T2 | Session manager core: statuses, deps, locks, CAS ledger writes, result/handoff/checkpoint records | done — see EPIC-001-STATUS.md |
| T3 | Orchestrator `alpa run/status/pause/resume/next/task finish/progress`, retries, usage-limit stop | done — see EPIC-001-STATUS.md |
| T4 | Hooks: SessionStart bounded context, Stop completion gate (T-069 regression), PreCompact snapshot | done — see EPIC-001-STATUS.md |
| T5 | Bootstrap defaults (config, settings, skills, rule, studio-start), Mission Control fields | done — see EPIC-001-STATUS.md |
| T6 | Versioned upgrade `alpa upgrade` (dry-run, active-session block, backup, validate, rollback) | done — see EPIC-001-STATUS.md |
| T7 | Tests: hermetic (fake claude) + real 3-task integration test | done — see EPIC-001-STATUS.md |
| T8 | Docs, CHANGELOG, version 0.3.0, Codex review package, migration dry-runs | done — see EPIC-001-STATUS.md |

Status of each task is recorded in `docs/epics/EPIC-001-STATUS.md` once work lands.
