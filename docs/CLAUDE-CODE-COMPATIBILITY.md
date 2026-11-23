# Claude Code compatibility

Validated design target: Claude Code 2.1.322 on 2026-11-11.

- Project settings and precedence: <https://code.claude.com/docs/en/settings>
- Custom project subagents in `.claude/agents/`: <https://code.claude.com/docs/en/sub-agents>
- Project skills in `.claude/skills/<name>/SKILL.md`: <https://code.claude.com/docs/en/skills>
- Lifecycle and safety hooks: <https://code.claude.com/docs/en/hooks-guide>
- Non-interactive `claude -p`, bounded turns and JSON output: <https://docs.anthropic.com/en/docs/claude-code/cli-usage>

Claude Code evolves. Before a framework release, run the automated suite plus `claude doctor` and manually verify `/agents`, `/skills`, and `/hooks` in an installed disposable Unity fixture. Project installation deliberately avoids modifying user-level Claude configuration.


## 0.3.0 notes (Claude Code 2.1.322)

- Hooks used: `SessionStart` (sources `startup`, `resume`, `clear`, `compact`), `Stop` (returns `decision: block`; honors `stop_hook_active` to avoid loops), `PreToolUse` (exit code 2 blocks), `PreCompact`.
- `/clear` only resets context and fires `SessionStart(source=clear)`; it does not execute anything. Hands-free rotation needs `alpa run`.
- Headless flags used: `-p`, `--output-format json`, `--max-turns`, `--permission-mode acceptEdits`, `--allowedTools`.
- Trust-dialog caveat: in a workspace that has not passed the trust dialog, `-p` mode ignores project `permissions.allow`. Since 0.3.1 the runner passes the complete local tool set through `--allowedTools`; deterministic hooks still block secrets, destructive Git, main/master pushes, paid services and publishing. Automatic Git writes are restricted to the current `alpa/<task-id>` branch.
- `bypassPermissions` and `--dangerously-skip-permissions` are forbidden.
- Process-name quirk: the installed binary is version-named (`2.1.322`), so `lsof -c claude` misses it. Live-session detection uses `ps` argv plus `lsof -p` for cwd.
