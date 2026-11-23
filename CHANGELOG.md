# Changelog

## 0.4.0 — 2026-11-23

Renamed to **Alpa Studio**. Upgrading from 0.3.x: see `docs/MIGRATION.md`.

- Renamed the product from AI Game Studio to Alpa Studio, the Python package from `ai_game_studio` to `alpa_studio` and the distribution to `alpa-studio`.
- Added the `alpa` CLI (`bin/alpa`, project-local `scripts/alpa`). `ags` stays as a deprecated alias: it prints a one-line notice to stderr and then behaves exactly like `alpa`. `AGS_*` environment variables are still read when the matching `ALPA_*` variable is unset.
- Renamed the project state dir from `.ai-game-studio` to `.alpa-studio`, the rule file to `.claude/rules/alpa-studio.md` and runner branches to `alpa/<task-id>`.
- Added automatic layout migration: `alpa upgrade --apply`, and any project command that finds only the legacy dir, moves `.ai-game-studio` to `.alpa-studio`, renames `scripts/ags` and the rule file, and rewrites manifest keys. It runs through the existing verified backup, ledger check and `--rollback` path.
- English-only pass: all CLI output, hook messages, session context, the Mission Control dashboard, templates and docs are now English. The owner's start/continue phrases are configurable through `execution.continue_phrases` (default `start`, `continue`); the session context marker is `ACTIVE TASK`.
- Template model policy: all production code, design, director and art roles run on `opus` (`unity-developer`, `backend-engineer`, `build-engineer`, `editor-tools-engineer` and `visual-qa` moved from `sonnet`). Implementers write production code only; test code is written and run by `gameplay-qa` on `sonnet`. The `/next-task` skill states this routing. The template generator now produces these files.
- Replaced the project-specific profiles with one generic `profiles/example.json`; `--profile` also accepts a path to a profile JSON file.
- Removed internal audit, dry-run and review artifacts that are not useful in a public repository.

## 0.3.2 — 2026-11-12

- Treat a recent final `Stop` hook as positive shutdown evidence when no project Claude process or runner remains, avoiding a false 15-minute upgrade block without weakening active-session protection.

## 0.3.1 — 2026-11-12

- Allowed autonomous sessions to use the complete local toolchain, web research and Git while retaining deterministic safety hooks.
- Added runner-managed `ags/<task-id>` branches; automatic commits require explicit paths and task IDs, and pushes are limited to the matching task branch.
- Added permission-denial fail-fast behavior so one infrastructure error stops the runner without terminally blocking the remaining queue.
- Added `ags task retry` and made backlog order explicitly priority-only rather than an implicit dependency.

## 0.3.0 — 2026-11-12

Autonomous context and session management (see `docs/CONTEXT-SESSION-MANAGEMENT.md`).

- Added `ags run`, an external orchestrator that starts one fresh `claude -p` session per task. Task outcomes come only from nonce-bound `results/<id>.json` records written by `ags task finish`.
- Added the Stop gate (blocks stopping without a valid result, bounded loop, includes the T-069 regression), a PreCompact checkpoint, bounded SessionStart context and Design Authority decision re-injection.
- Added approval and dependency buckets (`waiting_approval`, `blocked_dependency`) so independent tasks keep running.
- Added usage-limit handling (exit 75, task stays `interrupted`, backoff) and pause/resume (`ags pause`, `ags resume`, `ags status`).
- Added a single-runner lock, flock + CAS ledger writes and secret redaction in summaries, evidence, checkpoints and handoffs.
- Added `ags upgrade` (dry-run by default, refuses `--apply` on an active session, verified SHA-256 backup, `--rollback`).
- Added the Mission Control "Session / Runner" panel.

Fixes:

- The runner passes a narrow `--allowedTools` because untrusted workspaces ignore project `permissions.allow` in `-p` mode.
- Live-session detection uses `ps` argv; `lsof -c claude` misses the version-named binary (`2.1.322`).
- `.DS_Store` is excluded from the runtime copy.
- CLI upgrade no longer passes the nonexistent `force_inactive`.

## 0.2.4 — 2026-11-11

- Made the role-based Claude model policy part of the canonical agent generator and every installed agent definition.
- Assigned `opus` to studio/direction/architecture and all product, game, visual, UX, motion, audio and accessibility design roles; `haiku` to continuity/resource roles; and `sonnet` to implementation, research and QA roles.
- Added regression coverage so framework updates cannot silently remove explicit agent models.

## 0.2.3 — 2026-11-11

- Removed the hardcoded project CLI profile allowlist.
- Added validated discovery of any `profiles/<id>.json` profile, including actionable unknown-profile errors.
- Added a new-project profile and regression coverage for dynamic profile installation.

## 0.2.2 — 2026-11-11

- Made every installed project carry its own complete AI Game Studio runtime.
- Removed the project launcher's dependency on the framework checkout and all Codex workspace paths.
- Kept GitHub/the framework clone as installation and update input only.

## 0.2.1 — 2026-11-11

- Made the owner's start/continue prompt (then Turkish-only) a deterministic Studio resume trigger that executes the next eligible queued task.
- Added project-local `scripts/ags` and `scripts/studio-start.sh`; no global PATH installation is required.
- Studio startup now preserves existing work and begins with the persisted queue instead of re-bootstrapping the game.

## 0.2.0 — 2026-11-11

- Added recoverable legacy-project migration with `.claude` replacement, automatic backup, project-agent/rule preservation and runtime-package separation.
- Added `/next-task` compatibility workflow and migration of current command references without rewriting historical progress.
- Added canonical-document pointers, post-migration approval/task creation, and machine-readable migration record.

## 0.1.0 — 2026-11-11

- Production-grade portable MVP core.
- Safe isolated installer, 46 agents, six skills, deterministic hooks, Mission Control, approval/task/evidence/checkpoint/QA state, session runner, health checks, and two certification profiles.
- Initial environment audit and 22-test verification suite.

