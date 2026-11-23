# Evidence: what Alpa Studio did on real projects

These numbers come from one solo developer's machine, measured from the Claude Code transcripts
of five real projects between 2026-10-17 and 2026-11-23. Nothing here is a benchmark or a
simulation, and nothing was cherry-picked. The bad numbers are included as well.

You can reproduce the method on your own machine with `python3 tools/usage_scan.py --split <date>`
(see [Method](#method)).

## TL;DR

| What we measured | Before (10-17 → 10-28) | After (10-29 → 11-23) |
|---|---:|---:|
| Tokens per API turn | 221K | **70K (−68%)** |
| Peak context in any session | 965K | **130K** |
| Sessions with context > 500K | 3 | **0** |
| Satranc: tokens per finished backlog task | 61M | **21M (−66%)** |
| Blokku: tokens per commit | 7.9M | **3.6M (−54%)** |
| Commits across all repos | 684 in 12 days | ~1,530 in 26 days |
| New games started from the studio template | – | 2 (Mahjong, TimeTots) |
| **Total tokens per active day** | 431M | **517M (+20%)** ⚠️ |

**Honest summary.** Each task and each turn got much cheaper and much smaller. Context stopped
exploding. Total spend still went *up*, because we used the savings to run more work in
parallel, started two new games, and later chose an expensive review panel on purpose (see
[What did not work](#what-did-not-work)). Alpa Studio makes every unit of work cheaper. It does
not make you spend less unless you cap the amount of work.

## The projects

| Project | What it is | Studio setup |
|---|---|---|
| Satranc | Chess monorepo: two Unity mobile apps (adult puzzles + kids' chess school) and shared C# packages | Origin of the studio: lanes, 21-role panel, `/next-task` runner |
| Mahjong | Unity mobile tile game, started 2026-11-10 | Alpa Studio 0.3.2 template |
| TimeTots | Unity kids' app, started 2026-11-13 | Alpa Studio 0.3.2 template |
| Blokku | Unity block puzzle, already in progress | Token policy only (fresh session per task, model routing) |
| playzuru | Web project | Neither; it serves as a **control** |

"Before" and "after" are split at **2026-10-29**. On that date the token policy that became
Alpa Studio was switched on:

- one task per fresh session, with hand-off through files and git;
- an explicit model on every subagent;
- filtered tool output;
- compact or clear at fixed thresholds.

The studio template itself was extracted on 2026-11-10 and installed in Mahjong and TimeTots.

## 1. Context stopped exploding

| Session metric | Before | After |
|---|---:|---:|
| Main sessions | 12 | 664 |
| Peak context (largest single turn) | 965K | 130K |
| Sessions above 500K context | 3 | 0 |
| Median turns per session | 13 | 27 |

Before, a few huge sessions did everything. The worst was a web session of 1,396 turns over
four days that reached 965K context. Every turn re-read most of that context from cache, so
**97% of all tokens were cache reads**. After the switch, work was split into hundreds of short
sessions that start clean, and the context never went above 130K.

## 2. Each unit of work got cheaper

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Tokens per API turn (all projects) | 221K | 70K | −68% |
| Satranc, kids lane: finished tasks (from its progress log) | 18 | 202 | 11× |
| Satranc, kids lane: tokens per finished task | 61M | 21M | −66% |
| Blokku: tokens per commit | 7.9M | 3.6M | −54% |
| playzuru (control, no studio): tokens per commit | 2.6M | 2.6M | 0% |

The control project, which did not adopt the policy, did not change. The projects that adopted
it did.

## 3. Two new games built on the template

| Project | Calendar days | Commits | Test files | Tokens | Tokens per commit |
|---|---:|---:|---:|---:|---:|
| Mahjong | 13 (11-10 → 11-22) | 391 | 477 | 3.81B | 9.7M |
| TimeTots | 10 (11-13 → 11-22) | 160 | 193 | 2.59B | 16M |

Both projects were driven almost entirely by the unattended runner. Each backlog task ran in its
own `claude -p` process and was gated by tests and reviewers. The owner answered questions in
the approval queue.

## 4. Weekly volume (all projects)

| ISO week | Tokens | API turns |
|---|---:|---:|
| 43 | 793M | 3,822 |
| 44 | 3.93B | 21,488 |
| 45 | 2.02B | 27,350 |
| 46 | 3.83B | 54,882 |
| 47 | 6.22B | 93,727 |

The number of turns grew 25×, while tokens grew about 8×. More work ran on cheaper turns.

## What did not work

These problems are fixed or documented, so you can avoid them.

1. **Total spend went up, not down: 431M → 517M tokens per active day.** Cheaper work led to
   more work. If you need a budget, cap tasks per day in the runner (`alpa run --max-tasks`).
2. **A big review panel is expensive.** From 2026-11-16 Satranc ran a full panel of 21 reviewers
   on Opus for every task, with a score bar of 8.5. It raised quality, but it is the main reason
   week 47 is the most expensive week. Subagents are **64%** of all tokens after the switch.
   Start with developer → tester → one reviewer, and add panel roles only where your quality
   problems actually are.
3. **"Opus for everything" cancels most of the routing savings.** After the switch, Opus still
   produced 95% of main-session tokens and 74% of subagent tokens. Sonnet produced 25% of
   subagent tokens, and Haiku produced 1%. The template now uses Opus for implementers and
   Sonnet for test writing and running. Cheap roles such as search and lint-style verdicts
   should stay on Haiku.
4. **A runner that loops inside one process is not a fresh session.** Satranc's older runner
   called `/next-task` without a limit inside one `claude` process. One such session lasted 12
   days and 4,737 turns. Alpa Studio's `alpa run` starts **one process per task**, and that is
   the reason this release exists.
5. **Transcripts older than 30 days are deleted by default.** We lost all data from before
   2026-10-17, which is why the "before" window is short. Set `"cleanupPeriodDays": 90` in
   `~/.claude/settings.json` before you start measuring.

## Method

- **Source:** every `~/.claude/projects/**/*.jsonl` file, including `subagents/` transcripts.
  Each assistant message carries `message.usage`.
- **Deduplication:** by `requestId`, because one API response can appear on several transcript
  lines. Synthetic messages are skipped.
- **"Tokens":** input + output + cache creation + cache read. This is the volume of work, not
  the dollar cost; cache reads are billed far lower than fresh input.
- **Commits:** `git rev-list --count` per repository and time window. Duplicate working copies
  of the same repository are counted once.
- **Tasks:** checked lines in the lane's progress log, not commits.
- **Limits of the data:** one developer and one machine; the "before" window is only 9 active
  days; the project mix changed between the two windows. Treat the per-unit numbers (per turn,
  per task, per commit, the control project) as the evidence, not the totals.

Reproduce it on your own machine:

```bash
python3 tools/usage_scan.py --split 2026-10-29 --since 2026-09-01
```

The script only reads local files, prints a Markdown report, and never prints your home path.
