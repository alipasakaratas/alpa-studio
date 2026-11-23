"""Context & Session Manager + autonomous task orchestrator.

One logical task per fresh Claude process. Completion is decided from a recorded result
(`alpa task finish`), never from Claude's exit code or claims. All state lives under
`.alpa-studio/` and is written atomically; ledger updates are serialized with a file lock
and a monotonically increasing revision (compare-and-swap).

All owner-facing text is English; the owner's continue phrases are configurable
(`execution.continue_phrases`).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from . import legacy
from .util import atomic_json, now_iso, read_json

STATE_DIR = ".alpa-studio"
DONE = {"done", "completed"}
TERMINAL = DONE | {"failed", "blocked"}
FINISH_STATUSES = ("done", "blocked", "failed", "waiting_for_approval")
RUNNABLE = {"queued", "interrupted", "waiting_for_approval"}

EXIT_OK, EXIT_FATAL, EXIT_LOCKED, EXIT_USAGE_LIMIT = 0, 3, 4, 75

DEFAULT_EXECUTION: dict[str, Any] = {
    "policy": "auto",
    "task_source": "ledger",
    "backlog_file": "docs/BACKLOG.md",
    "backlog_prompt": "/next-task {id}",
    "max_attempts": 2,
    "max_turns": 40,
    "permission_mode": "acceptEdits",
    "model": None,
    "timeout_seconds": 3600,
    "backoff_seconds": [30, 120],
    "max_consecutive_infra_failures": 2,
    "context_budget_chars": 4000,
    "git_policy": "task-branches",
    # What the owner types to start the next task (any language); matched case-insensitively.
    "continue_phrases": ["start", "continue"],
}
DEFAULT_CONTINUE_PHRASES = ("start", "continue")

USAGE_LIMIT_RE = re.compile(
    r"usage limit|rate[ _-]?limit|limit reached|resets? at|too many requests|\b429\b|overloaded",
    re.IGNORECASE)
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|(?i:(?:api[_-]?key|token|secret|password|passwd)\s*[=:]\s*)[^\s'\"]{6,})")
BACKLOG_RE = re.compile(r"^\s*[-*] \[([ xX])\] \**([A-Z][A-Z0-9]*-\d+[A-Za-z]?)\**[:.)\s-]*(.*)$")


class SessionError(RuntimeError):
    pass


# --------------------------------------------------------------------------- paths & config

def _p(project: Path, *parts: str) -> Path:
    return project.joinpath(STATE_DIR, *parts)


def execution_config(project: Path) -> dict[str, Any]:
    config = read_json(_p(project, "config.json"), {}) or {}
    merged = dict(DEFAULT_EXECUTION)
    merged.update({k: v for k, v in (config.get("execution") or {}).items() if v is not None or k == "model"})
    if legacy.env("BACKOFF_SECONDS") is not None:  # tests / CI
        merged["backoff_seconds"] = [int(legacy.env("BACKOFF_SECONDS"))]
    return merged


def continue_phrases(cfg: dict[str, Any]) -> list[str]:
    """Owner phrases that mean "take the next task" (config `execution.continue_phrases`)."""
    raw = cfg.get("continue_phrases")
    if isinstance(raw, str):
        raw = [raw]
    phrases = [str(p).strip() for p in (raw or []) if str(p).strip()]
    return phrases or list(DEFAULT_CONTINUE_PHRASES)


def redact(text: str | None) -> str:
    return SECRET_RE.sub("[REDACTED]", text or "")


def _safe_read_json(path: Path, default: Any) -> Any:
    """Partially written / corrupt files are never trusted."""
    try:
        value = read_json(path, default)
        return default if value is None else value
    except (OSError, ValueError):
        return default


# --------------------------------------------------------------------------- locking

@contextlib.contextmanager
def _flock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_json(path: Path, mutate: Callable[[Any], Any], default: Any,
                expected_revision: int | None = None) -> Any:
    """Locked read-modify-write with a revision counter (CAS)."""
    with _flock(path.with_name(path.name + ".lock")):
        data = _safe_read_json(path, default)
        revision = int(data.get("revision", 0)) if isinstance(data, dict) else 0
        if expected_revision is not None and expected_revision != revision:
            raise SessionError(f"Concurrent update detected ({path.name} revision {revision}, expected "
                               f"{expected_revision}); re-read and retry the operation.")
        result = mutate(data)
        if isinstance(data, dict):
            data["revision"] = revision + 1
        atomic_json(path, data)
        return result


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_info(project: Path) -> dict[str, Any] | None:
    info = _safe_read_json(_p(project, "run", "runner.lock"), None)
    if not info:
        return None
    info["alive"] = info.get("host") == socket.gethostname() and _pid_alive(info.get("pid"))
    return info


def acquire_runner_lock(project: Path) -> Path:
    path = _p(project, "run", "runner.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            info = lock_info(project)
            if info and info["alive"]:
                raise SessionError(f"A runner is already active in this project (pid {info['pid']}, "
                                   f"started {info.get('started_at')}). A second runner was not started.")
            if info and info.get("host") not in (None, socket.gethostname()):
                raise SessionError(f"The runner lock belongs to another machine ({info.get('host')}); "
                                   "it was not removed without manual verification.")
            path.unlink(missing_ok=True)  # stale lock: owner process is gone
            continue
        with os.fdopen(fd, "w") as handle:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(), "started_at": now_iso()}, handle)
        return path
    raise SessionError("Could not acquire the runner lock.")


def release_runner_lock(project: Path) -> None:
    path = _p(project, "run", "runner.lock")
    info = _safe_read_json(path, None)
    if info and info.get("pid") == os.getpid():
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- task sources

def _approvals(project: Path) -> dict[str, dict[str, Any]]:
    data = _safe_read_json(_p(project, "approvals.json"), {"items": []})
    return {item["id"]: item for item in data.get("items", [])}


def _ledger_tasks(project: Path) -> list[dict[str, Any]]:
    return list(_safe_read_json(_p(project, "tasks.json"), {"items": []}).get("items", []))


def _backlog_tasks(project: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    path = project / cfg["backlog_file"]
    state = _safe_read_json(_p(project, "run", "backlog-state.json"), {"items": {}}).get("items", {})
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        match = BACKLOG_RE.match(line)
        if not match:
            continue
        checked, task_id, title = match.group(1).lower() == "x", match.group(2), match.group(3).strip()
        extra = state.get(task_id, {})
        status = "done" if checked else extra.get("status", "queued")
        if checked and extra.get("status") not in (None, "done", "completed"):
            status = "done"
        if not checked and "BLOCKED:" in line:
            status = "blocked"
        item = {"id": task_id, "title": title[:200], "status": status,
                "prompt": cfg["backlog_prompt"].format(id=task_id), "source": "backlog",
                "attempts": extra.get("attempts", 0), "session_ids": extra.get("session_ids", []),
                "last_error": extra.get("last_error"), "requires_approval": extra.get("requires_approval"),
                "needs_owner": "(human)" in line, "depends_on": extra.get("depends_on", [])}
        items.append(item)
    return items


def tasks(project: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = cfg or execution_config(project)
    if cfg["task_source"] == "backlog":
        return _backlog_tasks(project, cfg)
    return _ledger_tasks(project)


def update_task(project: Path, task_id: str, changes: dict[str, Any],
                cfg: dict[str, Any] | None = None, append_session: str | None = None) -> dict[str, Any]:
    cfg = cfg or execution_config(project)
    if cfg["task_source"] == "backlog":
        def mutate(data: dict[str, Any]) -> dict[str, Any]:
            item = data.setdefault("items", {}).setdefault(task_id, {"attempts": 0, "session_ids": []})
            item.update(changes)
            if append_session and append_session not in item.setdefault("session_ids", []):
                item["session_ids"].append(append_session)
            return dict(item, id=task_id)
        return update_json(_p(project, "run", "backlog-state.json"), mutate, {"schema": 1, "items": {}})

    def mutate_ledger(data: dict[str, Any]) -> dict[str, Any]:
        for item in data.setdefault("items", []):
            if item["id"] == task_id:
                item.update(changes)
                if append_session:
                    ids = item.setdefault("session_ids", [])
                    if append_session not in ids:
                        ids.append(append_session)
                return dict(item)
        raise SessionError(f"Task not found: {task_id}")
    return update_json(_p(project, "tasks.json"), mutate_ledger, {"schema": 1, "items": []})


def classify(project: Path, cfg: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Split tasks into eligible / waiting_approval / blocked_dependency / … buckets."""
    cfg = cfg or execution_config(project)
    items = tasks(project, cfg)
    approvals = _approvals(project)
    by_id = {item["id"]: item for item in items}
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in (
        "eligible", "waiting_approval", "blocked_dependency", "needs_owner", "running", "done",
        "failed", "blocked", "exhausted")}
    for item in items:
        status = item.get("status", "queued")
        if status in DONE:
            out["done"].append(item)
            continue
        if status == "running":
            out["running"].append(item)
            continue
        if status in ("failed", "blocked"):
            out[status].append(item)
            continue
        approval_id = item.get("requires_approval")
        approval = approvals.get(approval_id) if approval_id else None
        if approval_id and (not approval or approval.get("status") != "approved"):
            out["waiting_approval"].append({**item, "approval": approval})
            continue
        if item.get("needs_owner"):
            out["needs_owner"].append(item)
            continue
        missing = [dep for dep in item.get("depends_on") or []
                   if by_id.get(dep, {}).get("status") not in DONE]
        if missing:
            out["blocked_dependency"].append({**item, "waiting_on": missing})
            continue
        if int(item.get("attempts") or 0) >= int(cfg["max_attempts"]) and status == "interrupted":
            out["exhausted"].append(item)
            continue
        if status in RUNNABLE:
            out["eligible"].append(item)
    out["eligible"].sort(key=lambda item: (0 if item.get("status") == "interrupted" else 1,
                                           -int(item.get("priority") or 0)))
    return out


# --------------------------------------------------------------------------- markers & records

def marker(project: Path) -> dict[str, Any] | None:
    return _safe_read_json(_p(project, "run", "current-task.json"), None)


def start_task(project: Path, task_id: str | None = None, mode: str = "manual",
               cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind the current (or next) session to exactly one task."""
    cfg = cfg or execution_config(project)
    buckets = classify(project, cfg)
    if task_id is None:
        if not buckets["eligible"]:
            raise SessionError("No eligible task: " + _no_work_reason(buckets))
        task = buckets["eligible"][0]
    else:
        task = next((t for t in tasks(project, cfg) if t["id"] == task_id), None)
        if not task:
            raise SessionError(f"Task not found: {task_id}")
        if task.get("status") in DONE:
            raise SessionError(f"{task_id} is already done; not run again.")
    attempt = int(task.get("attempts") or 0) + 1
    record = {"task_id": task["id"], "title": task.get("title"), "nonce": uuid.uuid4().hex,
              "attempt": attempt, "mode": mode, "source": cfg["task_source"], "started_at": now_iso(),
              "runner_pid": os.getpid() if mode == "auto" else None, "session_id": None}
    atomic_json(_p(project, "run", "current-task.json"), record)
    update_task(project, task["id"], {"status": "running", "started_at": record["started_at"],
                                      "attempts": attempt}, cfg)
    return record


def retry_task(project: Path, task_id: str, reason: str = "owner-approved retry",
               cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Requeue a terminal task without deleting its result, handoff, or session history."""
    cfg = cfg or execution_config(project)
    task = next((t for t in tasks(project, cfg) if t["id"] == task_id), None)
    if not task:
        raise SessionError(f"Task not found: {task_id}")
    if task.get("status") in DONE or task.get("status") == "running":
        raise SessionError(f"{task_id} cannot be requeued from status: {task.get('status')}")
    return update_task(project, task_id, {
        "status": "queued", "attempts": 0,
        "last_error": f"requeued: {redact(reason)[:200]}",
        "completed_at": None,
    }, cfg)


def claim_session(project: Path, session_id: str | None) -> dict[str, Any] | None:
    """SessionStart: attach the Claude session id to an unclaimed marker."""
    current = marker(project)
    if not current or not session_id:
        return current
    if current.get("session_id") is None:
        current["session_id"] = session_id
        atomic_json(_p(project, "run", "current-task.json"), current)
    return current


def clear_marker(project: Path, nonce: str | None = None) -> None:
    current = marker(project)
    if current and (nonce is None or current.get("nonce") == nonce):
        _p(project, "run", "current-task.json").unlink(missing_ok=True)


def _parse_test(spec: str) -> dict[str, str]:
    parts = dict(part.split("=", 1) for part in spec.split(";") if "=" in part)
    result = parts.get("result", "unverified").strip().lower()
    if result not in {"passed", "failed", "unverified", "skipped"}:
        raise SessionError(f"Invalid test result '{result}' (passed|failed|unverified|skipped)")
    return {"cmd": redact(parts.get("cmd", spec)).strip(), "result": result,
            "note": redact(parts.get("note", "")).strip()}


def _git(project: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=str(project), text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def changed_files(project: Path, limit: int = 50) -> list[str]:
    lines = _git(project, "status", "--porcelain").splitlines()
    return [line[3:] for line in lines if not line[3:].startswith(STATE_DIR + "/")][:limit]


def finish_task(project: Path, task_id: str, status: str, summary: str, evidence: list[str] | None = None,
                tests_run: list[str] | None = None, next_actions: list[str] | None = None,
                approval_title: str | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record the outcome of a task. DONE without evidence or with a failing test is refused."""
    cfg = cfg or execution_config(project)
    if status not in FINISH_STATUSES:
        raise SessionError(f"Invalid status: {status} ({'|'.join(FINISH_STATUSES)})")
    task = next((t for t in tasks(project, cfg) if t["id"] == task_id), None)
    if not task:
        raise SessionError(f"Task not found: {task_id}")
    evidence = [redact(e).strip() for e in (evidence or []) if e and e.strip()]
    parsed_tests = [_parse_test(spec) for spec in (tests_run or [])]
    if status == "done":
        if not evidence:
            raise SessionError("DONE cannot be recorded without evidence. Add --evidence or use "
                               "--status blocked.")
        failing = [t["cmd"] for t in parsed_tests if t["result"] == "failed"]
        if failing:
            raise SessionError("DONE cannot be recorded while a test is failing: " + ", ".join(failing))
        missing_gates = [g for g in task.get("required_gates") or []
                         if not any(g in t["cmd"] and t["result"] == "passed" for t in parsed_tests)]
        if missing_gates:
            raise SessionError("Required gates did not pass or were not verified: " + ", ".join(missing_gates)
                               + ". If they cannot be verified, record them as 'unverified' with --status blocked.")
    current = marker(project)
    bound = current if current and current.get("task_id") == task_id else None
    approval_id = None
    if status == "waiting_for_approval":
        from .project import approval_create  # local import: avoid cycle
        approval_id = approval_create(project, approval_title or f"{task_id}: owner decision required",
                                      "design-authority", redact(summary))["id"]
    unverified = [t["cmd"] for t in parsed_tests if t["result"] in ("unverified", "skipped")]
    record = {
        "schema": 1, "task_id": task_id, "title": task.get("title"), "status": status,
        "summary": redact(summary).strip(), "evidence": evidence, "tests": parsed_tests,
        "unverified": unverified, "next_actions": [redact(n) for n in next_actions or []],
        "changed_files": changed_files(project), "head": _git(project, "rev-parse", "--short", "HEAD"),
        "recorded_at": now_iso(), "recorded_ts": time.time(),
        "nonce": bound.get("nonce") if bound else None,
        "session_id": bound.get("session_id") if bound else None,
        "attempt": bound.get("attempt") if bound else task.get("attempts"),
        "approval_id": approval_id,
    }
    atomic_json(_p(project, "results", f"{task_id}.json"), record)
    handoff = _render_handoff(record)
    for name in (f"{task_id}.md", "LATEST.md"):
        path = _p(project, "handoffs", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(handoff, encoding="utf-8")
        os.replace(tmp, path)
    changes: dict[str, Any] = {"status": status, "completed_at": record["recorded_at"],
                               "outcome": {"summary": record["summary"][:500], "unverified": unverified},
                               "result_file": f"{STATE_DIR}/results/{task_id}.json", "last_error": None}
    if approval_id:
        changes["requires_approval"] = approval_id
    if status in ("blocked", "failed"):
        changes["last_error"] = record["summary"][:300]
    update_task(project, task_id, changes, cfg)
    return record


def _render_handoff(record: dict[str, Any]) -> str:
    lines = [f"# Handoff — {record['task_id']}: {record.get('title') or ''}".rstrip(), "",
             f"- Status: **{record['status']}**", f"- Recorded: {record['recorded_at']}",
             f"- HEAD: {record.get('head') or '-'}", "", "## Summary", record["summary"] or "-", "",
             "## Evidence"]
    lines += [f"- {e}" for e in record["evidence"]] or ["- (none)"]
    lines += ["", "## Testler"]
    lines += [f"- `{t['cmd']}` → {t['result']}" for t in record["tests"]] or ["- (not run)"]
    if record["unverified"]:
        lines += ["", "## Unverified"] + [f"- {u}" for u in record["unverified"]]
    lines += ["", "## Changed files"] + ([f"- {f}" for f in record["changed_files"][:30]] or ["- (none)"])
    lines += ["", "## Next steps"] + ([f"- {n}" for n in record["next_actions"]] or ["- (none)"])
    return "\n".join(lines) + "\n"


def result_for(project: Path, task_id: str) -> dict[str, Any] | None:
    return _safe_read_json(_p(project, "results", f"{task_id}.json"), None)


def result_matches(record: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """A result counts only if it belongs to *this* attempt (nonce, or recorded after start)."""
    if not record or record.get("task_id") != current.get("task_id"):
        return False
    if record.get("nonce"):
        return record["nonce"] == current.get("nonce")
    try:
        started = datetime.fromisoformat(current["started_at"]).timestamp()
    except (KeyError, ValueError):
        return False
    return float(record.get("recorded_ts") or 0) >= started - 1


def progress(project: Path, task_id: str, phase: str, note: str = "", next_action: str = "",
             subtasks: list[str] | None = None, tests_status: str = "") -> dict[str, Any]:
    path = _p(project, "checkpoints", f"{task_id}-progress.json")
    entry = {"at": now_iso(), "phase": redact(phase), "note": redact(note)[:1000],
             "next_action": redact(next_action)[:500], "subtasks": [redact(s) for s in subtasks or []],
             "tests_status": redact(tests_status)[:300], "changed_files": changed_files(project, 30)}

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        items = data.setdefault("items", [])
        items.append(entry)
        del items[:-20]
        data["task_id"] = task_id
        return entry
    return update_json(path, mutate, {"schema": 1, "items": []})


def latest_progress(project: Path, task_id: str) -> dict[str, Any] | None:
    items = _safe_read_json(_p(project, "checkpoints", f"{task_id}-progress.json"), {"items": []})["items"]
    return items[-1] if items else None


def precompact_snapshot(project: Path, trigger: str = "auto", session_id: str | None = None) -> dict[str, Any]:
    current = marker(project)
    task_id = current.get("task_id") if current else None
    events = _safe_read_json(_p(project, "events.json"), {"items": []}).get("items", [])
    errors = [e for e in events[-200:] if e.get("blocked") or e.get("error")][-5:]
    snapshot = {
        "schema": 1, "at": now_iso(), "trigger": trigger, "session_id": session_id, "task": current,
        "progress": latest_progress(project, task_id) if task_id else None,
        "changed_files": changed_files(project, 40), "head": _git(project, "rev-parse", "--short", "HEAD"),
        "recent_errors": [{"tool": e.get("tool"), "reason": redact(str(e.get("reason", "")))[:200]}
                          for e in errors],
        "decisions": locked_decisions(project),
    }
    atomic_json(_p(project, "checkpoints", "precompact-latest.json"), snapshot)
    return snapshot


def locked_decisions(project: Path, limit: int = 8) -> list[str]:
    locks = _safe_read_json(_p(project, "locks.json"), {"paths": []}).get("paths", [])
    approved = [f"{a['id']}: {a['title']}" for a in _approvals(project).values()
                if a.get("category") == "design-authority" and a.get("status") == "approved"]
    return ([f"kilitli: {p}" for p in locks] + approved)[:limit]


# --------------------------------------------------------------------------- context injection

def _clip(text: str, max_lines: int, width: int = 220) -> str:
    lines = [line[:width] for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join(lines[:max_lines]) + ("\n…" if len(lines) > max_lines else "")


def session_context(project: Path, source: str = "startup") -> str:
    """Bounded, essential context for SessionStart (startup|resume|clear|compact)."""
    cfg = execution_config(project)
    config = _safe_read_json(_p(project, "config.json"), {})
    profile = (config.get("profile") or {}).get("name") or (config.get("profile") or {}).get("id") or "?"
    buckets = classify(project, cfg)
    current = marker(project)
    out = [f"[Alpa Studio] Project: {profile} · framework {config.get('framework_version', '?')} · "
           f"execution: {cfg['policy']} · source: {cfg['task_source']}"]
    if current:
        out.append(f"ACTIVE TASK: {current['task_id']} — {current.get('title') or ''} "
                   f"(attempt {current.get('attempt')}, mode {current.get('mode')}). This session is for this task ONLY.")
        prog = latest_progress(project, current["task_id"])
        if prog:
            out.append(f"Last checkpoint ({prog['at']}): phase={prog['phase']}; {prog['note'][:300]}; "
                       f"next={prog['next_action'][:200]}")
        if (current.get("attempt") or 1) > 1:
            out.append("The previous attempt was interrupted: do not repeat completed steps, and do not trust "
                       "half-written files without checking them.")
    else:
        out.append("No active task.")
    instruction_at = len(out)  # the finish/continue contract must survive budget clipping
    if source == "compact":
        snap = _safe_read_json(_p(project, "checkpoints", "precompact-latest.json"), None)
        if snap:
            files = ", ".join(snap.get("changed_files", [])[:15]) or "-"
            out.append(f"State before compaction ({snap['at']}): changed files: {files}")
    handoff = _p(project, "handoffs", "LATEST.md")
    if handoff.exists():
        out.append("Last handoff:\n" + _clip(handoff.read_text(encoding="utf-8"), 14))
    if buckets["eligible"]:
        out.append("Next eligible tasks: " + "; ".join(
            f"{t['id']} {str(t.get('title') or '')[:70]}" for t in buckets["eligible"][:3]))
    if buckets["waiting_approval"]:
        out.append("Waiting for owner approval: " + "; ".join(
            f"{t['id']} ({t.get('requires_approval')})" for t in buckets["waiting_approval"][:5]))
    if buckets["blocked_dependency"]:
        out.append("Blocked by dependencies: " + "; ".join(
            f"{t['id']}←{','.join(t['waiting_on'])}" for t in buckets["blocked_dependency"][:5]))
    decisions = locked_decisions(project)
    if decisions:
        out.append("Locked decisions (Design Authority): " + "; ".join(decisions)
                   + ". On conflict, do not implement; record --status waiting_for_approval with the reason and an alternative.")
    if current:
        out.insert(instruction_at, f"REQUIRED when finishing: scripts/alpa task finish --id {current['task_id']} --status "
                   "done|blocked|failed|waiting_for_approval --summary \"...\" --evidence \"...\" "
                   "--test \"cmd=...;result=passed\" --next \"...\". DONE without evidence is rejected. "
                   "For intermediate state: scripts/alpa task progress --id ... --phase ... --next ...")
    else:
        phrases = " / ".join(f"'{p}'" for p in continue_phrases(cfg))
        out.insert(instruction_at, f"If the owner says {phrases}: take the next task with scripts/alpa task start, "
                   "finish only that task and stop. Do not ask for a task id.")
    text = "\n".join(out)
    budget = int(cfg["context_budget_chars"])
    return text if len(text) <= budget else text[:budget - 1] + "…"


# --------------------------------------------------------------------------- orchestrator

def _no_work_reason(buckets: dict[str, list]) -> str:
    parts = []
    for key, label in (("waiting_approval", "waiting for approval"), ("blocked_dependency", "waiting on dependencies"),
                       ("needs_owner", "owner work"), ("blocked", "blocked"), ("failed", "failed"),
                       ("exhausted", "out of attempts"), ("running", "running")):
        if buckets.get(key):
            parts.append(f"{len(buckets[key])} {label}")
    return ", ".join(parts) or "queue empty"


def build_prompt(project: Path, task: dict[str, Any], record: dict[str, Any]) -> str:
    base = task.get("prompt") or task.get("title") or task["id"]
    contract = (
        f"\n\n---\nAlpa Studio automatic session. Task: {task['id']} (attempt {record['attempt']}). "
        "Do only this task; do not move on to another task. When the work is done, or if you cannot make "
        f"progress, you MUST run: scripts/alpa task finish --id {task['id']} --status done|blocked|failed|"
        "waiting_for_approval --summary \"<summary>\" --evidence \"<file/command output>\" "
        "--test \"cmd=<command>;result=passed|failed|unverified\" --next \"<next step>\". "
        "Without evidence, do not record done. If Unity or a tool is missing, record the test result as "
        "unverified; do not claim it passed. Backlog/document order is only a priority; only an explicitly "
        "declared depends_on is a dependency. "
        f"Your git branch is {record.get('branch') or 'alpa/<task-id>'}; once tests pass, stage only this "
        f"task's explicit files, commit with the message '{task['id']}: <summary>' and push only this same "
        "task branch to origin. Do not push to main/master, merge, tag, force-push, release or deploy.")
    if record["attempt"] > 1:
        prog = latest_progress(project, task["id"])
        if prog:
            contract += f" Last checkpoint of the previous attempt: {prog['phase']} — {prog['note'][:300]}."
    return base + contract


RUNNER_ALLOWED_TOOLS = (
    "Read", "Grep", "Glob", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent",
    "WebSearch", "WebFetch", "Bash(*)",
)


def task_branch_name(task_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", task_id.lower()).strip("-")
    return f"alpa/{slug or 'task'}"


def prepare_task_branch(project: Path, task_id: str, cfg: dict[str, Any]) -> str:
    """Put an automatic task on a reviewable branch without touching working-tree content."""
    current = _git(project, "branch", "--show-current")
    if cfg.get("git_policy") != "task-branches":
        return current
    target = task_branch_name(task_id)
    if current == target:
        return target
    exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target}"], cwd=str(project),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0
    command = ["git", "switch", target] if exists else ["git", "switch", "-c", target]
    changed = subprocess.run(command, cwd=str(project), text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, check=False)
    if changed.returncode != 0:
        raise SessionError(f"Could not prepare the task branch ({target}): {changed.stdout.strip()[:500]}")
    return target


def build_command(project: Path, task: dict[str, Any], record: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    mode = cfg["permission_mode"]
    if mode in ("bypassPermissions",) or "dangerous" in str(mode):
        raise SessionError("bypassPermissions is forbidden.")
    command = [legacy.env("CLAUDE_BIN", "claude"), "-p", build_prompt(project, task, record),
               "--output-format", "json", "--max-turns", str(cfg["max_turns"]), "--permission-mode", mode]
    if cfg.get("model"):
        command += ["--model", str(cfg["model"])]
    # Untrusted workspaces (e.g. a brand-new game dir) ignore project permissions.allow in -p mode,
    # so the runner grants the narrow studio-control commands explicitly. Never a bypass.
    allowed = list(RUNNER_ALLOWED_TOOLS) + [str(t) for t in (cfg.get("allowed_tools") or [])]
    command += ["--allowedTools", ",".join(dict.fromkeys(allowed))]
    return command


def _parse_claude_output(raw: str) -> dict[str, Any]:
    for line in reversed(raw.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    return value
            except ValueError:
                continue
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _spawn(command: list[str], project: Path, env: dict[str, str], log_path: Path,
           timeout: int) -> tuple[int, str, bool]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, cwd=str(project), env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    return proc.returncode, log_path.read_text(encoding="utf-8", errors="replace"), timed_out


def run_task(project: Path, cfg: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
    """Run exactly one task in one fresh Claude process and decide its outcome."""
    buckets = classify(project, cfg)
    selected = task_id or (buckets["eligible"][0]["id"] if buckets["eligible"] else None)
    if not selected:
        return {"task_id": "-", "kind": "git_preflight", "status": "interrupted",
                "error": "no eligible task"}
    try:
        branch = prepare_task_branch(project, selected, cfg)
    except SessionError as exc:
        return {"task_id": selected, "kind": "git_preflight", "status": "interrupted",
                "error": str(exc)}
    record = start_task(project, selected, mode="auto", cfg=cfg)
    record["branch"] = branch
    atomic_json(_p(project, "run", "current-task.json"), record)
    task = next(t for t in tasks(project, cfg) if t["id"] == record["task_id"])
    command = build_command(project, task, record, cfg)
    env = {**os.environ, "ALPA_TASK_ID": record["task_id"], "ALPA_TASK_NONCE": record["nonce"],
           "ALPA_RUN_MODE": "auto"}
    log = _p(project, "runs", f"{record['task_id']}-{record['attempt']}.log")
    started = time.time()
    try:
        code, raw, timed_out = _spawn(command, project, env, log, int(cfg["timeout_seconds"]))
    except OSError as exc:
        update_task(project, record["task_id"], {"status": "interrupted", "last_error": f"could not start: {exc}"}, cfg)
        clear_marker(project, record["nonce"])
        return {"task_id": record["task_id"], "kind": "infra", "status": "interrupted", "error": str(exc)}
    out = _parse_claude_output(raw)
    permission_denials = list(out.get("permission_denials") or [])
    session_id = out.get("session_id") or (marker(project) or {}).get("session_id")
    result = result_for(project, record["task_id"])
    valid = result_matches(result, record)
    outcome: dict[str, Any] = {"task_id": record["task_id"], "attempt": record["attempt"], "exit_code": code,
                               "session_id": session_id, "duration_s": round(time.time() - started, 1),
                               "log": str(log.relative_to(project)), "subtype": out.get("subtype"),
                               "cost_usd": out.get("total_cost_usd")}
    errored = code != 0 or bool(out.get("is_error")) or timed_out
    if valid and result.get("status") == "blocked" and permission_denials:
        denied = [str(item.get("tool_name") or "tool") + ": "
                  + str((item.get("tool_input") or {}).get("command") or "")[:160]
                  for item in permission_denials[:5]]
        outcome.update(kind="permission_denied", status="interrupted",
                       error="permission preflight failed: " + " | ".join(denied))
        changes = {"status": "interrupted", "attempts": max(0, record["attempt"] - 1),
                   "last_error": outcome["error"]}
    elif valid:
        status = result["status"]
        if status == "done" and not result.get("evidence"):
            status = "blocked"  # defence in depth: never accept evidence-free DONE
        outcome.update(kind="recorded", status=status, summary=result.get("summary"))
        changes: dict[str, Any] = {"status": status}
    elif errored and USAGE_LIMIT_RE.search(raw[-4000:]):
        outcome.update(kind="usage_limit", status="interrupted")
        changes = {"status": "interrupted", "last_error": "usage/rate limit — state saved",
                   "attempts": record["attempt"] - 1}  # a limit is not the task's fault
    else:
        exhausted = record["attempt"] >= int(cfg["max_attempts"])
        reason = ("timeout" if timed_out else "turn limit" if out.get("subtype") == "error_max_turns"
                  else f"claude exit code {code}" if errored else "no result record (alpa task finish was not called)")
        status = "blocked" if exhausted else "interrupted"
        outcome.update(kind="infra" if errored and not out else "no_result", status=status, error=reason)
        changes = {"status": status, "last_error": f"{reason}; not verified" + (" — out of attempts" if exhausted else "")}
    update_task(project, record["task_id"], changes, cfg, append_session=session_id)
    _append_history(project, outcome)
    clear_marker(project, record["nonce"])
    return outcome


def _append_history(project: Path, outcome: dict[str, Any]) -> None:
    def mutate(data: dict[str, Any]) -> None:
        items = data.setdefault("history", [])
        items.append({**outcome, "at": now_iso()})
        del items[:-200]
    update_json(_p(project, "run", "run-state.json"), mutate, {"schema": 1, "history": []})


def _set_runner_state(project: Path, **fields: Any) -> None:
    def mutate(data: dict[str, Any]) -> None:
        data.setdefault("runner", {}).update(fields)
    update_json(_p(project, "run", "run-state.json"), mutate, {"schema": 1, "history": []})


def recover_orphans(project: Path, cfg: dict[str, Any]) -> list[str]:
    """Called while holding the runner lock: any 'running' task belongs to a dead runner."""
    recovered = []
    current = marker(project)
    for item in tasks(project, cfg):
        if item.get("status") == "running":
            if current and current.get("mode") == "manual" and current.get("task_id") == item["id"]:
                continue  # an interactive owner session owns it
            update_task(project, item["id"], {"status": "interrupted",
                                              "last_error": "previous runner was interrupted; can be resumed"}, cfg)
            recovered.append(item["id"])
    if current and current.get("mode") == "auto":
        clear_marker(project)
    return recovered


def run(project: Path, max_tasks: int | None = None, dry_run: bool = False,
        overrides: dict[str, Any] | None = None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    cfg = execution_config(project)
    cfg.update({k: v for k, v in (overrides or {}).items() if v is not None})
    if dry_run:
        buckets = classify(project, cfg)
        plan = []
        for task in buckets["eligible"][: max_tasks or None]:
            fake = {"attempt": int(task.get("attempts") or 0) + 1, "nonce": "dry-run"}
            plan.append({"task_id": task["id"], "title": task.get("title"),
                         "command": shlex.join(build_command(project, task, fake, cfg))})
        return {"stop_reason": "dry_run", "exit_code": EXIT_OK, "plan": plan, "runs": [],
                "pending": _no_work_reason(buckets)}
    try:
        acquire_runner_lock(project)
    except SessionError as exc:
        return {"stop_reason": "locked", "exit_code": EXIT_LOCKED, "error": str(exc), "runs": []}
    runs: list[dict[str, Any]] = []
    stop_reason, exit_code, consecutive_infra = "no_eligible", EXIT_OK, 0
    try:
        recovered = recover_orphans(project, cfg)
        _set_runner_state(project, pid=os.getpid(), status="running", started_at=now_iso(),
                          recovered=recovered, stop_reason=None)
        while True:
            if _p(project, "run", "PAUSE").exists():
                stop_reason = "paused"
                break
            if max_tasks is not None and len(runs) >= max_tasks:
                stop_reason = "max_tasks"
                break
            buckets = classify(project, cfg)
            if not buckets["eligible"]:
                stop_reason = ("waiting_for_owner" if buckets["waiting_approval"] or buckets["needs_owner"]
                               else "no_eligible")
                break
            outcome = run_task(project, cfg)
            runs.append(outcome)
            if outcome["kind"] in ("permission_denied", "git_preflight"):
                stop_reason, exit_code = "preflight_failed", EXIT_FATAL
                break
            if outcome["kind"] == "usage_limit":
                stop_reason, exit_code = "usage_limit", EXIT_USAGE_LIMIT
                break
            if outcome["kind"] in ("infra", "no_result") and outcome.get("error", "").startswith(("claude exit code", "could not start")):
                consecutive_infra += 1
                if consecutive_infra >= int(cfg["max_consecutive_infra_failures"]):
                    stop_reason, exit_code = "infra_failures", EXIT_FATAL
                    break
            else:
                consecutive_infra = 0
            if outcome["status"] == "interrupted":
                backoff = list(cfg["backoff_seconds"]) or [0]
                sleep(backoff[min(outcome.get("attempt", 1) - 1, len(backoff) - 1)])
    except Exception as exc:  # fatal: persist and stop safely
        stop_reason, exit_code = "fatal", EXIT_FATAL
        runs.append({"kind": "fatal", "error": redact(str(exc))})
    finally:
        _set_runner_state(project, status="stopped", stopped_at=now_iso(), stop_reason=stop_reason)
        release_runner_lock(project)
    return {"stop_reason": stop_reason, "exit_code": exit_code, "runs": runs,
            "pending": _no_work_reason(classify(project, cfg))}


def pause(project: Path, reason: str = "") -> dict[str, Any]:
    path = _p(project, "run", "PAUSE")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": now_iso(), "reason": redact(reason)}), encoding="utf-8")
    return {"paused": True, "note": "The runner stops after the running task finishes; the active session is not interrupted."}


def resume(project: Path) -> dict[str, Any]:
    _p(project, "run", "PAUSE").unlink(missing_ok=True)
    return {"paused": False}


def status(project: Path) -> dict[str, Any]:
    cfg = execution_config(project)
    buckets = classify(project, cfg)
    state = _safe_read_json(_p(project, "run", "run-state.json"), {"history": []})
    return {
        "execution": {k: cfg[k] for k in ("policy", "task_source", "max_attempts", "max_turns", "permission_mode", "model")},
        "runner": {**(state.get("runner") or {}), "lock": lock_info(project),
                   "paused": _p(project, "run", "PAUSE").exists()},
        "current_task": marker(project),
        "counts": {k: len(v) for k, v in buckets.items()},
        "eligible": [{"id": t["id"], "title": t.get("title")} for t in buckets["eligible"][:10]],
        "waiting_approval": [{"id": t["id"], "title": t.get("title"), "approval": t.get("requires_approval")}
                             for t in buckets["waiting_approval"]],
        "blocked_dependency": [{"id": t["id"], "waiting_on": t["waiting_on"]} for t in buckets["blocked_dependency"]],
        "pending_approvals": [a for a in _approvals(project).values() if a.get("status") == "pending"],
        "last_runs": state.get("history", [])[-5:],
    }


STOP_LABELS = {
    "no_eligible": "No eligible task left", "waiting_for_owner": "Remaining work is waiting for owner approval or owner work",
    "max_tasks": "Task limit reached", "paused": "Paused by the owner", "usage_limit":
    "Usage/rate limit — state saved; resume with `scripts/alpa run` once the limit resets",
    "infra_failures": "Consecutive infrastructure failures — runner stopped safely", "fatal": "Fatal error — state saved",
    "locked": "A runner is already active", "dry_run": "Dry run (nothing was run)",
    "preflight_failed": "Permission/Git preflight failed — runner stopped without blocking tasks",
}


def summarize(result: dict[str, Any]) -> str:
    lines = [f"Alpa Studio runner: {STOP_LABELS.get(result['stop_reason'], result['stop_reason'])}."]
    for item in result.get("runs", []):
        if item.get("kind") == "fatal":
            lines.append(f"  ✗ error: {item.get('error')}")
            continue
        mark = {"done": "✓", "completed": "✓", "waiting_for_approval": "⏸"}.get(item.get("status"), "•")
        detail = item.get("summary") or item.get("error") or ""
        lines.append(f"  {mark} {item['task_id']} → {item.get('status')} (attempt {item.get('attempt')}, "
                     f"session {str(item.get('session_id') or '-')[:8]}) {str(detail)[:120]}")
    for item in result.get("plan", []):
        lines.append(f"  → {item['task_id']} {item.get('title') or ''}")
    if result.get("error"):
        lines.append("  " + result["error"])
    if result.get("pending"):
        lines.append(f"Pending: {result['pending']}")
    return "\n".join(lines)


def which_claude() -> str | None:
    return shutil.which(legacy.env("CLAUDE_BIN", "claude"))
