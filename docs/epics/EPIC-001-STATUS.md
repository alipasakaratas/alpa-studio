# EPIC-001 status — framework 0.3.2

## 0.3.1 verification note

The runner can now use local tests, production tools, web research and Git. Safety hooks block
destructive commands, credentials, unapproved paid-service/publishing actions and Git writes outside
the task branch. The hermetic suite passed with 63 tests (1 real-Claude test skipped as opt-in).
This is automated verification, not an independent security certification. The records below show
the historical first verification at the 0.3.0 stage.

## Summary

The code is complete and passed the hermetic tests; the real-Claude 3-task test passed (3 separate sessions, zero intervention). Upgrades of two private pilot projects were run as dry-runs only (MIGRATION_READY) and were NOT APPLIED because of live sessions. The Codex review was not run (Codex CLI broken). The owner's next step: close the sessions and run `alpa upgrade --apply`.

## Tasks

| ID | Task | Status |
|----|------|--------|
| T1 | Inspect the framework and two private pilot projects | done |
| T2 | Session manager core | done, hermetic tests pass |
| T3 | Orchestrator (`alpa run/status/pause/resume/...`) | done, hermetic + real test pass |
| T4 | Hooks (SessionStart, Stop gate, PreCompact) | done, hermetic tests pass |
| T5 | Bootstrap defaults, Mission Control panel | done |
| T6 | `alpa upgrade` | done; dry-run only on real projects, apply NOT run |
| T7 | Tests (hermetic + real) | done |
| T8 | Docs, CHANGELOG, version 0.3.0, review package, dry-runs | done; Codex review NOT run |

## VERIFIED

- Hermetic suite: 58 tests OK (1 skipped = the real test, run separately).
- Real test (`RealClaudeIntegrationTest`): 3 tasks, 3 distinct `session_id`s, `stop_reason` `no_eligible`, zero intervention, model haiku, about $0.02 total. Evidence: `docs/epics/evidence/real-claude-3-tasks.json`.
- The first real run failed on a permission denial; fixed by passing `--allowedTools`, then re-run passed.
- Pilot project dry-runs (0.2.2 -> 0.3.0 and 0.2.4 -> 0.3.0): `MIGRATION_READY`, each blocked by a live Claude session. Both read-only, tree digest unchanged (the raw dry-run reports were private and are not published).

## NOT VERIFIED

- Upgrades are NOT applied to the pilot projects (owner must close sessions first).
- Codex review not run (CLI unavailable). An external review package (not published).
- Unity gates on real projects.
- Long-run usage-limit recovery against real limits (only simulated).

## Next steps for owner

1. Close the live Claude sessions in the pilot projects.
2. Re-run `alpa upgrade --project <P>` (add `--task-source backlog` where the project keeps a backlog file), review, then `--apply`.
3. Run `scripts/alpa status` and `scripts/alpa run --dry-run` in each project.
4. Repair the Codex CLI and run the review package, or review manually.
5. Run a supervised real session with Unity gates and a real usage limit.
