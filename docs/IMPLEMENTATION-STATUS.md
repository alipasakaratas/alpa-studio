# Implementation status — 0.4.0

| Capability | Status | Evidence / boundary |
|---|---|---|
| Separate versioned repository | Implemented | Local Git repository, VERSION, changelog, license |
| One-command safe installer | Implemented | Dry-run default; `--apply`; preflight, merge, backup, hashes, conflicts |
| Project-isolated runtime/agents/skills/hooks/docs | Implemented | Complete local runtime, 46 agents, seven skills, hooks, rules, studio docs; no checkout dependency |
| Recoverable legacy migration | Implemented | Replaces Claude control plane; backs up originals; preserves project agents/rules, product work and runtime packages |
| Studio Director and need-based roles | Implemented | Role catalog and routing instructions; Claude decides actual delegation |
| Real competitor/video/review research | Partial | Source ledger and specialist workflow work; automatic crawling is not bundled |
| Art Bible, Game Bible, Master Asset, three concepts | Implemented workflow | Templates, owner gates, locks; game-specific content is not fabricated |
| Multi-stage independent Visual QA, 95 target | Implemented core | Weighted ledger and certification gate; real screenshots/video still required |
| AI image generation | Planned / not implemented | Provider selection, credentials, spend, licensing and generation require approval |
| 3D/Blender pipeline | Planned / not implemented | Blender detection works; generation/import/render automation not implemented |
| Unity Editor integration | Planned / not implemented | Unity version detection works; batch tests/build/import automation not executed |
| Branch/worktree automation | Partial | Runner creates and pushes only `alpa/<task-id>` branches; full separate-worktree isolation remains planned |
| Checkpoint | Implemented | Non-destructive HEAD/branch/dirty/diff-stat ledger |
| Automatic rollback | Planned / not implemented | Intentionally excluded because rollback can destroy uncommitted work |
| Session rotation / persistent runner | Implemented | Durable queue; one fresh bounded Claude process per task; no bypass permissions |
| Model/resource/storage manager | Partial | Tool/hardware/disk checks and safe concurrency recommendation; dynamic model routing not forced |
| iPhone Simulator testing | Capability unavailable here | Xcode exists, but no available iOS runtime/device was detected on 2026-11-11 |
| Android emulator testing | Configured, not run | Three AVD definitions found; no running or physical device detected |
| Physical Android testing | Not available | No connected ADB device detected on 2026-11-11 |
| Mission Control | Implemented MVP | Local dashboard, asset gallery, health, tasks, QA, approval mutation |
| Security/copyright/child compliance | Implemented gates | Checklists, agents, hooks; current legal/store review remains a release-time task |
| Paid service/publishing owner gate | Implemented | Approval records + hooks; no store upload is performed |
| Project certification | Workflow implemented, no project certified | Profile-driven gates (`profiles/example.json`); see `docs/CERTIFICATION-PLAN.md` |

