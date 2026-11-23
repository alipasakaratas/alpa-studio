---
description: Selects and completes one open project backlog task through the Alpa Studio lifecycle. Use when the owner invokes /next-task, optionally with a task ID.
argument-hint: "[task-id]"
---

Complete exactly one task (from `docs/BACKLOG.md` or the `.alpa-studio/tasks.json` ledger, per `execution.task_source`). One task per session.

1. Read `docs/studio/STATUS.md`, `CLAUDE.md`, the backlog line, relevant canonical decisions, current Git status and the latest progress handoff. Preserve unrelated dirty work.
2. If the SessionStart context names an ACTIVE TASK, that is the task. Else if `$ARGUMENTS` names a task, run `scripts/alpa task start --id $ARGUMENTS`; otherwise run `scripts/alpa task start` (first eligible: not done, not `BLOCKED:`, not `(human)`, approvals granted, dependencies done). Never ask the owner for a task ID. Backlog/document order is priority only, never an implicit dependency; only explicit `depends_on` metadata blocks a task.
3. Studio Director selects only the necessary specialists. An implementer never provides the final independent review of its own change.
4. Create a checkpoint (`scripts/alpa task progress --id <ID> --phase ... --next ...`) and repeat it after each meaningful step. Confirm Unity is not holding this project before batchmode work.
5. Model routing (owner, 2026-11-12): all production code, all design work, directors and art specialists run on opus; test code is written and run by gameplay-qa on sonnet. Implement acceptance criteria without changing approved design authority. New paid services, prices, SDKs, publishing, or design changes go to the approval queue.
6. Run proportionate tests. For visual work require in-engine captures; unavailable evidence is NOT RUN.
7. Run tester and plan-reviewer equivalents using the relevant QA roles. Maximum three fix rounds; then mark the task `BLOCKED:` with concrete findings and finish with `--status blocked`.
8. Only after acceptance: check the backlog item (backlog source), append `docs/PROGRESS.md`, stage explicit task-owned paths (never `git add .`/`-A`), commit as `<TASK-ID>: <summary>`, and push only the runner-created `alpa/<task-id>` branch. Never push main/master, merge, tag, force-push, release or deploy automatically.
9. Always record the outcome: `scripts/alpa task finish --id <ID> --status done|blocked|failed|waiting_for_approval --summary "<summary>" --evidence "<evidence>" --test "cmd=<command>;result=passed|failed|unverified" --next "<next step>"`. Then stop. Do not start another task in this session; autonomous mode opens a fresh session for the next one.
