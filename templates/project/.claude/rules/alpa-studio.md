# Alpa Studio project policy

This project uses Alpa Studio {{FRAMEWORK_VERSION}} with profile `{{PROFILE_ID}}`.

- The owner is the final design authority. Approved Art Bible, Game Bible, Master Asset, references, mechanics, prices, paid services, and publishing decisions are immutable until the owner approves a change request.
- Start from `docs/studio/STATUS.md`; persist handoffs in files instead of relying on chat history.
- Use only the specialist roles needed for the current task. Independent reviewers must not review their own work.
- Research claims require real, dated URLs. Never invent competitor, video, review, legal, device, or test evidence.
- Use feature branches/worktrees for isolated changes. Never force-push, publish, upload, buy, or activate a paid service without explicit owner approval.
- A missing tool, simulator, device, screenshot, video, log, or score is NOT IMPLEMENTED/NOT VERIFIED, never PASS.
- Visual quality target is 95/100 internally, but the numeric score never overrides the approved design.
- When the owner says one of the configured continue phrases (`execution.continue_phrases` in `.alpa-studio/config.json`; default `start`, `continue`) or asks to resume the studio, automatically use `/studio-start`. Do not re-bootstrap an existing game and do not ask for a task ID.
- **Context & session management (mandatory):** one logical task per Claude session. The default is autonomous mode: `scripts/studio-start.sh` / `scripts/alpa run` launches a fresh Claude process per task. Manual fallback: `/clear` then a continue phrase (default `continue`).
- Bind the session to one task with `scripts/alpa task start` (next eligible) unless the SessionStart context already names an ACTIVE TASK. Record checkpoints with `scripts/alpa task progress`.
- End every task with `scripts/alpa task finish --id <ID> --status done|blocked|failed|waiting_for_approval --summary ... --evidence ... --test "cmd=...;result=..." --next ...`. DONE without evidence is refused; unavailable Unity/device gates are `unverified`, never passed. After finishing, stop: do not start an unrelated task in the same session.
- A conflict with a locked decision is never implemented: record it with the reason and alternatives using `--status waiting_for_approval`; independent tasks continue.
- Write owner-facing summaries, handoffs and status messages in English unless the project CLAUDE.md names another owner language.

