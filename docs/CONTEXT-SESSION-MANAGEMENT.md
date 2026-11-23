# Context & Session Management (0.3.2)

Every project installed or upgraded with Alpa Studio 0.3.0+ gets this system. That includes every new game created from it. It is not optional and it is not per-project code: the runtime is copied to `.alpa-studio/runtime/src`, and the hooks in `.claude/` call it.

## Principle: one logical task per fresh Claude session

Each task runs in its own Claude session with a clean context. A session ends in one of four terminal states: `done`, `blocked`, `failed` or `waiting_for_approval`. Once a session reaches one of these, it does not start an unrelated task.

## Modes

| Mode | How it starts | Owner action |
|---|---|---|
| **auto (default)** | `scripts/studio-start.sh` → `scripts/alpa run` | none |
| manual fallback | interactive `claude`, then `/clear` → a continue phrase (default `start` / `continue`, configurable via `execution.continue_phrases`) | typing a continue phrase once per task |
| interactive | `scripts/studio-start.sh --interactive` | — |

### How auto mode works

`alpa run` is a persistent external orchestrator. It is not a Claude feature. For each task it does the following:

1. Takes the single-runner lock at `run/runner.lock`. The lock is created with O_EXCL. A lock left by a dead pid on the same host is cleared; a lock held by a live process, or one from another host, refuses the run.
2. Recovers orphaned `running` tasks. A runner that died mid-task leaves its task `running`; recovery sets it to `interrupted` and it runs again.
3. Selects the first eligible task, writes `run/current-task.json` with a fresh nonce, and starts **one new** process:

   ```
   claude -p <prompt + one-task contract> --output-format json --max-turns N --permission-mode acceptEdits
   ```

   The runner passes the complete local tool set through `--allowedTools` (extendable via `execution.allowed_tools`). This is required because headless `-p` sessions cannot answer permission prompts. It is never `bypassPermissions`: project hooks still block secrets, destructive commands, paid services, release/deploy operations and unsafe Git. Each automatic task runs on `alpa/<task-id>`; explicit-path commits and pushes to that same branch are allowed, while main/master, merge, tag and force-push remain blocked.

   The environment carries `ALPA_TASK_ID`, `ALPA_TASK_NONCE` and `ALPA_RUN_MODE=auto`. stdin is closed, the process gets its own process group, and a timeout kills the whole group.
4. Decides the outcome only from `results/<id>.json`, written by `scripts/alpa task finish`. The record must carry the same nonce. Exit codes, git state and handoff files are never treated as completion.
5. Moves to the next task.

The loop stops when one of these happens:

- no eligible task remains;
- only owner-gated work remains (`waiting_for_owner`);
- `--max-tasks` is reached;
- `run/PAUSE` exists (`alpa pause`);
- a usage or rate limit is hit (exit 75, the task stays `interrupted`, and the attempt is not counted);
- consecutive infrastructure failures occur (exit 3);
- a tool permission or Git branch preflight fails (exit 3 immediately; the task remains resumable);
- a fatal error occurs (exit 3, with state persisted).

`/clear` never executes anything by itself. In Claude Code 2.1.322 it only resets context and fires `SessionStart(source=clear)`. Hands-free rotation therefore needs the external runner.

## Task sources

- `ledger` (default): `.alpa-studio/tasks.json`. It supports `depends_on`, `requires_approval`, `required_gates`, `acceptance` and `priority`.
- `backlog`: `docs/BACKLOG.md` checkbox lines such as `- [ ] M-153 …`.
  - Lines containing `BLOCKED:` are blocked.
  - Lines marked `(human)` are owner work.
  - Runner state lives in `run/backlog-state.json`; the runner never rewrites the owner's backlog.
  - The prompt is `/next-task {id}`.

Classification buckets: `eligible`, `waiting_approval`, `blocked_dependency` (with `waiting_on`), `needs_owner`, `running`, `done`, `failed`, `blocked`, `exhausted`. Independent tasks keep running while approval-gated tasks and their dependents wait.

## Gates (no false DONE)

`alpa task finish --status done` is refused in three cases:

- there is no `--evidence`;
- any `--test` is `result=failed`;
- a task's `required_gates` has not passed (an `unverified` test result, e.g. Unity unavailable, is not a pass; record `blocked` with `unverified`).

The runner adds a second line of defence: an evidence-free `done` is downgraded to `blocked`.

**Stop hook.** When a session is bound to a task, the Stop hook works like this:

- **Binding:** the env nonce matches the marker, or the manual marker was claimed by this session.
- **No valid result:** stopping is blocked with exact `task finish` instructions. This happens at most twice per nonce, and `stop_hook_active` never loops.
- **Valid result:** a system message confirms it. In manual mode the marker is cleared, so the next continue phrase takes a fresh task.
- **Other sessions:** they are never gated.

**T-069 regression.** In an earlier pilot project, a handoff and a ledger change committed in the same commit made an *old* result look like the current session's completion. Here a result counts only when its nonce matches the current attempt, or for nonce-less legacy records, when `recorded_ts` is not earlier than `started_at`. Git state is never used. The scenario is covered by `tests/test_session.py::GateTests::test_stop_gate_t069_…`.

## Context injection and compaction

- **SessionStart** (all sources) injects a bounded context. Its size is capped by `execution.context_budget_chars` (4000 by default). The finish/continue contract is placed before the clipped sections, so it is never truncated. The context contains:
  - the project line;
  - the active task, its attempt and its last checkpoint;
  - the finish contract;
  - on `compact`, the pre-compaction snapshot;
  - the last handoff (≤14 lines);
  - the next three eligible tasks;
  - approval and dependency blocks;
  - locked Design Authority decisions.
- **PreCompact** writes `checkpoints/precompact-latest.json`. It holds the task, latest progress, changed files, HEAD, recent blocked tool calls and decisions. It is read back by SessionStart(compact).
- `alpa task progress` appends checkpoints to `checkpoints/<id>-progress.json` and keeps the last 20. A retried attempt receives the last checkpoint in its prompt.

## Design Authority

Locked paths (`locks.json`) cannot be edited without a `design-authority` approval; PreToolUse blocks the edit. Approved decisions are re-injected into every new session. A conflict is never implemented. It is recorded as `--status waiting_for_approval`, which creates a pending approval, and independent work continues.

## State layout (`.alpa-studio/`)

```
config.json            execution.{policy,task_source,max_attempts,max_turns,permission_mode,model,…}
tasks.json             ledger (revisioned; flock + CAS)
approvals.json, events.json, locks.json
run/runner.lock        single runner (pid, host)
run/current-task.json  session ↔ task binding (nonce, attempt, session_id)
run/run-state.json     runner state + last 200 run outcomes
run/PAUSE              owner pause flag
run/backlog-state.json backlog source state
results/<id>.json      authoritative task outcome
handoffs/<id>.md, handoffs/LATEST.md   handoffs
checkpoints/           progress + pre-compaction snapshots
runs/<id>-<attempt>.log  headless Claude output (secrets redacted in records)
upgrade-backups/       verified SHA-256 backups of upgrades (never deleted)
```

All JSON writes are atomic (temp file + `os.replace`). Read-modify-write goes through `update_json`, which takes an exclusive `flock` and increments `revision`. A caller can pass `expected_revision` (CAS). Secrets (`sk-…`, `ghp_…`, AWS keys, private keys, `token=…`) are redacted from summaries, evidence, checkpoints and handoffs.

## Commands

```
scripts/alpa run [--max-tasks N] [--dry-run] [--model haiku] [--json]   # autonomous (default)
scripts/alpa pause [--reason …] | resume [--no-run] | status | next | context --source clear
scripts/alpa task start [--id ID]      # manual: bind this session to the next eligible task
scripts/alpa task progress --id ID --phase … --note … --next …
scripts/alpa task finish --id ID --status done|blocked|failed|waiting_for_approval \
    --summary "…" --evidence "…" --test "cmd=…;result=passed|failed|unverified" --next "…"
alpa upgrade --project P [--task-source backlog] [--apply] [--rollback BACKUP_DIR]
```

`alpa upgrade --apply` is refused while the project is in use. It finds live Claude Code processes by their argv (`ps`) and their working directory (`lsof -p`). It does not use `lsof -c claude`, because the installed binary is version-named and lsof reports it as e.g. `2.1.322`. It also checks for a live runner lock and for hook events in the last 15 minutes.

Mission Control (`alpa dashboard`) shows the following panel: **Session / Runner** (mode, runner, active task, counts). `/api/state` returns `session`.

## Verification

- The hermetic suite `tests/test_session.py` uses a fake `claude` binary that really runs the project hooks and `scripts/alpa`.
- The real test is opt-in: `ALPA_REAL_CLAUDE=1 PYTHONPATH=src python3 -m unittest tests.test_session.RealClaudeIntegrationTest`. It runs 3 sequential tasks in 3 distinct real Claude sessions with zero intervention. Pass `ALPA_REAL_MODEL` to choose the model; the default is haiku.
