# Alpa Studio

**English** · [Türkçe](README.tr.md)

Alpa Studio is a local-first, versioned Claude Code framework for Unity iOS/Android production. It installs an isolated `.claude/` studio and `docs/studio/` governance layer into each game without changing global Claude, Unity, Xcode, Android, Blender, shell, or credential configuration.

Version: **0.4.0 MVP** · License: Apache-2.0 · Runtime dependencies: Python 3.9+, Git, Claude Code; Unity is required only for Unity execution.

## Evidence from real projects

Measured from the Claude Code transcripts of five real projects: two Unity games built from
this template, plus the chess project it was extracted from. The numbers compare the period
before the studio's session policy with the period after it.

| | Before | After |
|---|---:|---:|
| Tokens per API turn | 221K | **70K (−68%)** |
| Peak context in any session | 965K | **130K** |
| Tokens per finished task (chess project) | 61M | **21M (−66%)** |
| Tokens per commit (block-puzzle project) | 7.9M | **3.6M (−54%)** |
| Tokens per commit (control project without the studio) | 2.6M | 2.6M |
| Total tokens per active day | 431M | 517M (**+20%**, more work was run) |

The full numbers, what did not work, the method, and a script to reproduce the measurement on
your own machine are in [docs/EVIDENCE.md](docs/EVIDENCE.md)
(`python3 tools/usage_scan.py --split <date>`).

### Audio made on the developer's own machine

In these projects, every sound was produced on the developer's own computer. No cloud voice
service and no per-clip fees were involved.

- **Narration (voice-over):**
  - Generated with an open-source multilingual text-to-speech model (Chatterbox Multilingual)
    that runs from a local AI-models folder on Apple Silicon, fully offline.
  - The model speaks Turkish and English from the same lesson text. The kids' chess app ships
    **148 Turkish narration clips** for its first world. English uses the same pipeline and is
    switched on per language.
  - Each line has a fixed seed, so the same text gives the same clip. Clips are checked
    automatically, and a clip whose text has changed is muted until it is regenerated.
- **Sound effects and music:** synthesised by small Python scripts that use only the standard
  library. No samples or downloads are involved, and the script, not the WAV file, is the
  source of truth.

Alpa Studio does not bundle these models or scripts. They live in each game's `Tools/` folder.
The studio's audio and narrative roles plan the work, and the agents run the local tools.

## What works now

- Safe installer with mandatory Unity/Git/writability preflight, dry-run by default, conflict skipping, settings-preserving merge, backups, checksums, and project-local state.
- Complete project-local runtime; installed games do not depend on the framework checkout.
- 46 project-scoped Claude subagents, seven on-demand skills, deterministic hooks, minimal standing context, and autonomous full-tool execution constrained by project safety hooks and task branches.
- Explicit role-based model policy: direction, architecture, every creative/design role and all production-code roles use Opus; test code is written and run by `gameplay-qa` on Sonnet, as are research and the remaining QA roles; continuity/resource roles use Haiku.
- Studio Director routing, owner approval queue, immutable-decision locks, paid-service/publishing gates, source evidence ledger, persistent task queue, and one-fresh-Claude-session-per-task runner with reviewable task branches.
- Truthful health checks for Claude, Unity, Git, Python, Blender, ffmpeg, Android AVD/device state, iOS Simulator runtime/device state, hardware, memory, and storage.
- Localhost-only Mission Control with approval actions, task/QA state, asset gallery, and capability status.
- Weighted six-axis Visual QA with an internal 95/100 target; independent-review identity is required for certification.
- Non-destructive Git checkpoint ledger, data-driven certification profiles (`profiles/example.json` or your own JSON), and explicit child/privacy/security/rights gates.
- Python standard-library core: no package download and no paid runtime service.

## Honest MVP boundary

See [Implementation status](docs/IMPLEMENTATION-STATUS.md). In particular, image/3D generation providers, Blender execution pipelines, full task-worktree isolation, destructive rollback, real build/device execution, store submission, hosted multi-user Mission Control, and automatic legal conclusions are **planned/not implemented**. The framework detects and gates these capabilities; it does not pretend to have run them.

## Safe install

The first command is always a read-only plan:

```sh
./install.sh --project /absolute/path/to/UnityProject --profile example
```

Review the JSON actions. Apply only after the preflight and conflict list are acceptable:

```sh
./install.sh --project /absolute/path/to/UnityProject --profile example --apply
```

`example` is a neutral built-in profile. For your own game, copy `profiles/example.json`, edit it, and pass its path (`--profile path/to/my-game.json`) or add it as `profiles/<id>.json`; any validated profile is accepted without changing Python code. The installer never edits user-level `~/.claude` files. Existing project `.claude/settings.json` values are preserved; framework hooks and deny rules are merged. Unknown existing files are skipped and reported rather than overwritten.

## Daily commands

```sh
# Machine and project truth
./bin/alpa doctor --project /path/to/game

# Queue a critical decision
./bin/alpa approval create --project /path/to/game \
  --title "Choose the approved art concept" --category design-authority

# Add work; attach --requires-approval APR-... when needed
./bin/alpa task add --project /path/to/game --title "Research competitors" \
  --prompt "Run source-backed competitor, video, and review research."

# Show the next fresh Claude session without running it; add --execute deliberately
./bin/alpa runner --project /path/to/game

# Local Mission Control
./bin/alpa dashboard --project /path/to/game

# Honest certification report (non-zero until every gate has evidence)
./bin/alpa certify --project /path/to/game
```

## Daily use: auto mode (default)

```sh
scripts/studio-start.sh     # or: scripts/alpa run  -- one fresh Claude session per task
scripts/alpa status          # runner, active task, approvals, dependencies
scripts/alpa pause           # stop after the current task
scripts/alpa resume
```

Manual fallback: start `claude` interactively, run `/clear`, then type a continue phrase (default `start` or `continue`). `/clear` alone executes nothing. The phrases are configurable in `.alpa-studio/config.json` under `execution.continue_phrases`, for example `["start", "continue", "weiter"]`. Details: [docs/CONTEXT-SESSION-MANAGEMENT.md](docs/CONTEXT-SESSION-MANAGEMENT.md). Upgrade an installed project with `alpa upgrade` (see [docs/MIGRATION.md](docs/MIGRATION.md)).

## Existing project migration

Migration replaces only the legacy Claude control plane. It creates a recoverable backup, installs Alpa Studio, restores project-specific agents/rules as extensions, preserves game code/assets/docs and keeps existing Unity runtime packages until a deliberate package migration.

```sh
# Review only
./bin/alpa migrate --project /path/to/game --profile example

# Explicit replacement after review
./bin/alpa migrate --project /path/to/game --profile example --apply --replace-claude
```

In Claude Code, start with `/studio-start`. The current Claude Code project-scoped locations and hook structure follow Anthropic's current subagent, skill, settings, and hook documentation.

For an installed existing project, either run `scripts/studio-start.sh` or start `claude` in the project and say `start` (or another configured continue phrase). Studio Director resumes persisted state and executes the first eligible queued task.

## Repository map

```text
bin/alpa                         portable launcher
src/alpa_studio/                installer, health, workflow, dashboard
templates/project/.claude/      46 agents, seven skills, hooks, settings, rules
templates/project/docs/studio/  bibles, decisions, QA, research, safety
profiles/                       example.json; add your own profile JSON
tests/                          integration and safety tests
tools/usage_scan.py             measure token usage from your own transcripts
docs/                           architecture, status, audit, certification
```

## Development and verification

```sh
python3 scripts/generate_templates.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Generated agent templates are deterministic. `scripts/generate_templates.py` is the source for their shared structure; individual installed projects remain independent copies.

## Upgrading from AI Game Studio 0.3.x

Alpa Studio 0.4.0 was previously called AI Game Studio (CLI `ags`). `ags` still works as a deprecated alias that prints a one-line notice and then behaves like `alpa`; `AGS_*` environment variables are read when the matching `ALPA_*` one is unset. A project that still has `.ai-game-studio/` is migrated to `.alpa-studio/` by `alpa upgrade --apply` or automatically by the first project command, with a verified backup. Details: [docs/MIGRATION.md](docs/MIGRATION.md).

## Projects with an existing Claude setup

If a game already uses another Claude plugin, its own agents or local Unity packages, use `alpa migrate` (review first, then `--apply --replace-claude`). Compare package ownership, plugin names, hooks and approved game documents before installing; nothing is replaced without an explicit apply.
