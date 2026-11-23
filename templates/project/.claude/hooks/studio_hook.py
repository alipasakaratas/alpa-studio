#!/usr/bin/env python3
"""Deterministic Claude Code safety, continuity and completion hook (Alpa Studio).

Events: PreToolUse (safety), SessionStart (bounded context), PreCompact (snapshot),
Stop (completion gate). Fails open on internal errors except for explicit safety blocks.
Owner-facing text is English; the continue phrases come from execution.continue_phrases.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def append_event(root, event):
    path = root / ".alpa-studio/events.json"
    if not path.parent.is_dir():
        return
    with open(path.with_name("events.json.lock"), "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        data = load(path, {"schema": 1, "items": []})
        data.setdefault("items", []).append(event)
        data["items"] = data["items"][-2000:]
        tmp = path.with_name(f".events.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)


def approval(root, category):
    data = load(root / ".alpa-studio/approvals.json", {"items": []})
    return any(x.get("category") == category and x.get("status") == "approved" for x in data["items"])


def block(message, root=None, event=None):
    if root is not None and event is not None:
        try:
            append_event(root, {**event, "blocked": True, "reason": message[:300]})
        except OSError:
            pass
    print(message, file=sys.stderr)
    raise SystemExit(2)


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


def runtime(root):
    src = root / ".alpa-studio/runtime/src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from alpa_studio import session  # noqa: WPS433 (runtime import)
    return session


payload = json.load(sys.stdin)
root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".").resolve()
event_name = payload.get("hook_event_name", "unknown")
session_id = payload.get("session_id")
event = {"at": now(), "event": event_name, "session_id": session_id}
if payload.get("tool_name"):
    event["tool"] = payload.get("tool_name")
if event_name != "PreToolUse":
    try:
        append_event(root, event)
    except OSError:
        pass

if event_name == "PreToolUse":
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    command = str(tool_input.get("command", ""))
    lowered = command.lower()
    always_block = [r"\brm\s+-[^\n]*r[^\n]*f", r"git\s+reset\s+--hard", r"git\s+clean\s+-[^\n]*f",
                    r"git\s+push[^\n]*--force", r"\bsudo\s+", r"security\s+delete-",
                    r"--dangerously-skip-permissions", r"bypasspermissions"]
    if tool == "Bash" and any(re.search(pattern, lowered) for pattern in always_block):
        block("Alpa Studio blocked a destructive command. Use a reviewed, reversible alternative.",
              root, event)
    if tool == "Bash" and re.search(
        r"(?:^|[\s/])(?:\.env(?:\.|\s|$)|[^\s]+\.(?:p12|keystore)|\.ssh/|credentials(?:\s|$))",
        lowered,
    ):
        block("Automated commands cannot access sensitive credential/key files.", root, event)
    publish = ["fastlane deliver", "fastlane pilot", "fastlane supply", "upload_to_app_store",
               "xcrun altool", "xcrun notarytool", "gradle publish", "app-store upload"]
    if tool == "Bash" and any(marker in lowered for marker in publish) and not approval(root, "publish"):
        block("Publishing/uploading requires an approved 'publish' record in Mission Control.", root, event)
    paid = ["api.replicate.com", "api.openai.com", "api.elevenlabs.io", "meshy.ai", "luma.ai"]
    if tool == "Bash" and any(marker in lowered for marker in paid) and not approval(root, "paid-service"):
        block("Using a paid service requires an approved 'paid-service' record.", root, event)
    if tool == "Bash" and os.environ.get("ALPA_RUN_MODE") == "auto" and re.search(r"\b(?:alpa|ags)\s+task\s+(start|finish)", lowered):
        bound = os.environ.get("ALPA_TASK_ID", "")
        if re.search(r"\b(?:alpa|ags)\s+task\s+start", lowered):
            block(f"This automatic session is for {bound} only; no other task can be started.", root, event)
        match = re.search(r"--id[ =]+['\"]?([A-Za-z0-9_-]+)", command)
        if match and match.group(1) != bound:
            block(f"This automatic session can only record task {bound} (requested: {match.group(1)}).", root, event)
    if tool == "Bash" and os.environ.get("ALPA_RUN_MODE") == "auto" and re.search(r"\bgit\s+", lowered):
        bound = os.environ.get("ALPA_TASK_ID", "")
        slug = re.sub(r"[^a-z0-9-]+", "-", bound.lower()).strip("-")
        expected = f"alpa/{slug or 'task'}"
        actual = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(root), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        ).stdout.strip()
        mutation = re.search(
            r"\bgit\s+(add|commit|push|merge|rebase|tag|stash|switch|checkout|restore|branch)\b", lowered)
        if mutation and actual != expected:
            block(f"Automated Git writes are only allowed on the task branch: expected {expected}, current {actual}.",
                  root, event)
        if re.search(r"\bgit\s+(merge|rebase|tag|stash|switch|checkout|restore|branch)\b", lowered):
            block("An automatic session cannot switch branches or merge/rebase/tag/stash; the runner manages the branch.",
                  root, event)
        if re.search(r"\bgit\s+add\b", lowered):
            if re.search(
                r"\bgit\s+add\s+(?:-a\b|-u\b|--all\b|--update\b|(?:--\s+)?\.\s*(?:$|[;&|])|:/)",
                lowered,
            ):
                block("Bulk git add is forbidden; stage only the explicit file paths of the task.", root, event)
            if re.search(r"[;&|`]|\$\(", command):
                block("Do not chain the git stage command with other shell commands.", root, event)
        if re.search(r"\bgit\s+commit\b", lowered):
            if re.search(r"\bgit\s+commit\b[^\n]*(?:\s-[a-z]*a[a-z]*\b|\s--all\b)", lowered):
                block("git commit -a/--all is forbidden; stage only the explicit task files first.", root, event)
            if bound.lower() not in lowered:
                block(f"The commit message must start with the task id: {bound}: <summary>.", root, event)
            staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"], cwd=str(root), text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
            ).stdout.splitlines()
            sensitive = [p for p in staged if re.search(r"(?:^|/)(?:\.env(?:\.|$)|[^/]+\.(?:p12|keystore))", p)]
            if sensitive:
                block("Sensitive files cannot be committed: " + ", ".join(sensitive[:5]), root, event)
        if re.search(r"\bgit\s+push\b", lowered):
            allowed_push = re.fullmatch(
                rf"\s*git\s+push\s+origin\s+{re.escape(expected)}\s*", command, flags=re.IGNORECASE)
            if not allowed_push:
                block(f"Automated push is only allowed to the task branch: git push origin {expected}", root, event)
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if file_path:
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        protected = load(root / ".alpa-studio/locks.json", {"paths": []}).get("paths", [])
        rel = str(candidate.resolve().relative_to(root)) if root in candidate.resolve().parents else "OUTSIDE"
        if rel in protected and not approval(root, "design-authority"):
            block("An approved (locked) decision cannot be changed without design-authority approval: "
                  f"{rel}. Record the conflict with reasons and alternatives and send it for owner approval.", root, event)
    raise SystemExit(0)

try:
    session = runtime(root)
except Exception:  # runtime missing/broken: fail open with legacy summary
    session = None

if event_name == "SessionStart":
    if session is None:
        tasks = load(root / ".alpa-studio/tasks.json", {"items": []}).get("items", [])
        approvals = load(root / ".alpa-studio/approvals.json", {"items": []}).get("items", [])
        queued = sum(x.get("status") == "queued" for x in tasks)
        pending = sum(x.get("status") == "pending" for x in approvals)
        print(f"Alpa Studio active. Queued tasks: {queued}; pending owner approvals: {pending}. "
              "Read docs/studio/STATUS.md first.")
        raise SystemExit(0)
    try:
        current = session.marker(root)
        if current and os.environ.get("ALPA_TASK_NONCE") == current.get("nonce"):
            session.claim_session(root, session_id)
        context = session.session_context(root, payload.get("source", "startup"))
    except Exception as exc:  # never break session start
        context = f"Alpa Studio context could not be loaded ({type(exc).__name__}); read docs/studio/STATUS.md."
    emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}})
    raise SystemExit(0)

if event_name == "PreCompact" and session is not None:
    try:
        session.precompact_snapshot(root, payload.get("trigger", "auto"), session_id)
    except Exception:
        pass
    raise SystemExit(0)

if event_name == "Stop" and session is not None:
    try:
        current = session.marker(root)
    except Exception:
        current = None
    if not current:
        raise SystemExit(0)
    env_nonce = os.environ.get("ALPA_TASK_NONCE")
    if env_nonce:
        bound = env_nonce == current.get("nonce")
    elif current.get("mode") == "manual" and not current.get("session_id"):
        current = session.claim_session(root, session_id) or current
        bound = True
    else:
        bound = bool(session_id) and current.get("session_id") == session_id
    if not bound:
        raise SystemExit(0)  # another session's task: not ours to gate
    task_id = current["task_id"]
    record = session.result_for(root, task_id)
    if session.result_matches(record, current):
        status = record.get("status")
        message = (f"Task {task_id} was recorded as '{status}'. No other task is started in this session.")
        if current.get("mode") == "manual":
            session.clear_marker(root, current.get("nonce"))
            try:
                phrase = session.continue_phrases(session.execution_config(root))[0]
            except Exception:
                phrase = "continue"
            message += f" For the next task, type /clear and say '{phrase}' (automatic mode: scripts/alpa run)."
        emit({"systemMessage": message})
        raise SystemExit(0)
    if payload.get("stop_hook_active"):
        raise SystemExit(0)  # second pass: never loop
    counter = root / f".alpa-studio/run/stop-blocks-{current.get('nonce')}.json"
    count = load(counter, {"count": 0}).get("count", 0)
    if count >= 2:
        emit({"systemMessage": f"Warning: no result record for {task_id}; the task will not count as DONE and "
                                "will be marked unverified."})
        raise SystemExit(0)
    counter.parent.mkdir(parents=True, exist_ok=True)
    counter.write_text(json.dumps({"count": count + 1}), encoding="utf-8")
    emit({"decision": "block", "reason": (
        f"No result record for task {task_id}. Before stopping, run: scripts/alpa task finish "
        f"--id {task_id} --status done|blocked|failed|waiting_for_approval --summary \"...\" "
        "--evidence \"...\" --test \"cmd=...;result=passed|unverified\" --next \"...\". "
        "If it is not complete or cannot be verified, use --status blocked; never invent success.")})
    raise SystemExit(0)
