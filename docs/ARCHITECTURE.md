# Architecture

## Boundaries

The framework repository is immutable input to a project installation. Each Unity project receives independent copies under `.claude/` and `docs/studio/`, plus its complete runtime and machine-readable state under `.alpa-studio/`. The installed project does not call back into the framework checkout. No global configuration is required.

```text
framework version 0.3.2
  -> preflight + dry-run + reviewed apply
    -> Unity project-local agents / skills / hooks / docs
      -> persistent JSON control plane
        -> Claude sessions, Mission Control, QA and certification
```

`settings.json` uses Claude Code project scope. Existing dictionaries are recursively preserved, lists are de-duplicated, and scalar conflicts keep the user's value. Other unknown project files are skipped. Managed framework files use manifest SHA-256 hashes; locally modified managed files are not silently replaced.

## Control plane

State files are atomic JSON documents: approvals, tasks, events, QA, evidence, checkpoints, certifications, locks, configuration, and manifest. Mission Control binds only `127.0.0.1` and uses a per-process CSRF token for mutations. Asset serving is restricted to `docs/studio/assets`.

## Session control plane

```text
alpa run (runner, single-runner lock)
  -> fresh `claude -p` process per task (env: ALPA_TASK_ID, ALPA_TASK_NONCE)
    -> hooks: SessionStart (bounded context), PreToolUse (locks), PreCompact (checkpoint), Stop (completion gate)
      -> `scripts/alpa task finish`
        -> .alpa-studio/results/<id>.json (nonce-bound; the only completion authority)
```

The runner never trusts exit codes or git state. State layout (`run/`, `results/`, `handoffs/`, `checkpoints/`, `runs/`, `upgrade-backups/`) is documented in `docs/CONTEXT-SESSION-MANAGEMENT.md`.

## Context and tokens

Only short descriptions for 46 roles load at startup. Detailed procedures live in skills and load on demand. Agent frontmatter carries an explicit role-based model policy: direction, architecture and every product/game/visual/UX/motion/audio/accessibility design role use Opus; continuity/resource roles use Haiku; implementation, research and QA roles use Sonnet. The runner executes one bounded `claude -p` process per eligible task; project files, checkpoints, and handoffs are the durable memory. It never uses permission bypass mode.

## Safety model

Project hooks reject destructive shell patterns and gate publishing and known paid-service endpoints on explicit approval records. Approved design documents may be added to the lock list. The safety layer is defense-in-depth, not a shell sandbox; review and operating-system permissions still matter.

