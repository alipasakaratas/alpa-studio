---
description: Starts or resumes the Alpa Studio workflow from persistent project evidence. Use when the owner gives a game idea or asks to continue production.
---

Treat the owner's continue phrases (`execution.continue_phrases` in `.alpa-studio/config.json`; default `start` and `continue`, set your own in any language) as direct invocations of this skill. The SessionStart context already lists the active task, last handoff and next eligible tasks; trust it before re-reading files.

1. Read `docs/studio/STATUS.md`, immutable decisions, Git status, installation config, pending approvals, tasks, QA, and evidence.
2. Run the local health check. Do not install, update, authenticate, publish, or buy anything.
3. Select the smallest useful role set; Studio Director coordinates.
4. Existing project: preserve all current work and start the first eligible queued task immediately with `scripts/alpa task start` (or continue the ACTIVE TASK), then follow `/next-task` for that single task and finish with `scripts/alpa task finish`. Do not stop at a status report and do not recreate existing bibles or game systems. If a queued task is approval-bound, continue the next independent task.
5. New project only: obtain real competitor, video, and review evidence, then create Game Bible and three visual concepts.
6. Queue only critical owner approvals. Continue independent work while approval-bound tasks wait.
7. Persist checkpoint and handoff (`scripts/alpa task progress` / `scripts/alpa task finish`). Never claim certification before all gates have evidence.
8. One task per session: after `task finish`, tell the owner (in the owner language named by the project CLAUDE.md, English by default) what was done and stop. For hands-free production the owner runs `scripts/studio-start.sh` (autonomous `alpa run`).
9. Backlog order expresses priority, not dependency. Only explicit `depends_on` metadata may block an otherwise eligible task. Automatic sessions may test, commit and push their isolated `alpa/<task-id>` branch, but never main/master or a release.

