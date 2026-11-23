"""Versioned, idempotent framework upgrade for an installed project.

Dry-run by default. Apply is refused while any Claude session, runner or recent hook activity
uses the project (a momentarily unchanged file is not proof of quiescence). Apply takes a
verified SHA-256 backup, merges (never replaces) configuration, validates that task/approval
history is unchanged, and records a rollback point. Nothing is deleted.

A pre-0.4.0 layout (`.ai-game-studio`, `scripts/ags`) is renamed to the new layout after the
backup is taken, so the same backup also rolls the rename back.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from . import legacy
from .util import atomic_json, now_iso, project_root, read_json, sha256

STATE_DIR = legacy.STATE_DIR
SKIP_STATE = {"runtime", "backups", "upgrade-backups", "migration-backups", "runs"}
ACTIVITY_WINDOW_S = 15 * 60


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in str(value).split(".")[:3])
    except ValueError:
        return (0,)


def _claude_pids() -> list[int]:
    """PIDs of Claude Code processes. Matched by argv, not by command name: the installed binary
    is a version-named file (lsof reports e.g. '2.1.322'), so `lsof -c claude` misses live sessions."""
    out = subprocess.run(["ps", "-axo", "pid=,args="], text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, timeout=15, check=True).stdout
    pids = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        argv0 = parts[1].split()[0]
        if Path(argv0).name == "claude" or "/claude/versions/" in argv0 or "/@anthropic-ai/claude-code/" in parts[1]:
            pids.append(int(parts[0]))
    return [pid for pid in pids if pid != os.getpid()]


def claude_processes_in(project: Path) -> list[dict[str, Any]]:
    """Claude processes whose working directory is inside the project (ps + lsof)."""
    try:
        pids = _claude_pids()
        if not pids:
            return []
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-p", ",".join(map(str, pids)), "-Fpn"], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return [{"pid": None, "reason": "process list unreadable; cannot prove that no session is active"}]
    found, pid = [], None
    root = str(project.resolve())
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            cwd = line[1:]
            if cwd == root or cwd.startswith(root + "/"):
                found.append({"pid": pid, "cwd": cwd, "reason": "active Claude session"})
    return found


def active_session_blockers(project: Path) -> list[dict[str, Any]]:
    from .session import lock_info
    process_blockers = list(claude_processes_in(project))
    blockers = list(process_blockers)
    info = lock_info(project)
    if info and info.get("alive"):
        blockers.append({"pid": info.get("pid"), "reason": "running alpa runner"})
    events = read_json(project / _state_dir(project) / "events.json", {"items": []}) or {"items": []}
    items = events.get("items") or []
    if items:
        try:
            last = datetime.fromisoformat(items[-1]["at"])
            age = (datetime.now(timezone.utc) - last).total_seconds()
            # A final Stop event plus no project Claude/runner process is positive evidence that
            # the session has closed. Other recent events remain a conservative blocker.
            clean_stop = (items[-1].get("event") == "Stop" and not process_blockers
                          and not (info and info.get("alive")))
            if age < ACTIVITY_WINDOW_S and not clean_stop:
                blockers.append({"pid": None, "reason": f"last hook activity {int(age)} s ago"})
        except (KeyError, ValueError, TypeError):
            pass
    return blockers


def _state_dir(project: Path) -> str:
    return legacy.LEGACY_STATE_DIR if legacy.has_legacy_layout(project) else STATE_DIR


def _ledger_fingerprint(project: Path) -> dict[str, Any]:
    state_dir = _state_dir(project)
    tasks = (read_json(project / state_dir / "tasks.json", {"items": []}) or {}).get("items", [])
    approvals = (read_json(project / state_dir / "approvals.json", {"items": []}) or {}).get("items", [])
    counts = {}
    for name, key in (("checkpoints.json", "items"), ("evidence.json", "sources"), ("qa.json", "reviews")):
        counts[name] = len((read_json(project / state_dir / name, {key: []}) or {}).get(key, []))
    return {"tasks": {t["id"]: t.get("status") for t in tasks},
            "approvals": {a["id"]: a.get("status") for a in approvals}, "counts": counts}


def _backup_targets(project: Path) -> list[Path]:
    targets: list[Path] = []
    state = project / _state_dir(project)
    for path in sorted(state.rglob("*")) if state.is_dir() else []:
        rel = path.relative_to(state)
        if path.is_file() and rel.parts[0] not in SKIP_STATE and not path.name.endswith(".lock"):
            targets.append(path)
    for rel in (".claude", "scripts"):
        base = project / rel
        if base.is_dir():
            targets += [p for p in sorted(base.rglob("*")) if p.is_file()]
    for rel in ("CLAUDE.md",):
        if (project / rel).is_file():
            targets.append(project / rel)
    return targets


def make_backup(project: Path) -> Path:
    root = project / _state_dir(project) / "upgrade-backups" / now_iso().replace(":", "-")
    files: dict[str, str] = {}
    for path in _backup_targets(project):
        rel = str(path.relative_to(project))
        dest = root / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        files[rel] = sha256(path)
    for rel, digest in files.items():  # verify before anything is changed
        if sha256(root / "files" / rel) != digest:
            raise RuntimeError(f"Backup could not be verified: {rel}")
    atomic_json(root / "manifest.json", {"schema": 1, "created_at": now_iso(), "files": files})
    return root


def rollback(project: Path, backup: Path) -> dict[str, Any]:
    manifest = read_json(backup / "manifest.json")
    if not manifest:
        raise RuntimeError(f"Backup manifest missing: {backup}")
    for rel, digest in manifest["files"].items():
        if sha256(backup / "files" / rel) != digest:
            raise RuntimeError(f"Backup is corrupt; nothing was rolled back: {rel}")
    for rel in manifest["files"]:
        dest = project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / "files" / rel, dest)
    return {"ok": True, "restored": len(manifest["files"]), "backup": str(backup),
            "note": "Files added by the upgrade were not deleted (backed-up files were only restored)."}


def upgrade(project_arg: str | Path, apply: bool = False, task_source: str | None = None,
            rollback: str | None = None) -> dict[str, Any]:
    from .project import StudioError, installation_plan, install, require_install
    project = project_root(project_arg)
    if rollback:
        if active_session_blockers(project):
            raise StudioError("Rollback is not possible while a session is active.")
        return globals()["rollback"](project, Path(rollback) if Path(rollback).is_absolute() else project / rollback)
    legacy_renames = legacy.legacy_plan(project)
    config = (read_json(project / legacy.LEGACY_STATE_DIR / "config.json", None) if legacy_renames
              else None) or require_install(project)
    profile_id = (config.get("profile") or {}).get("id")
    current = config.get("framework_version", "0")
    plan = installation_plan(project, profile_id)
    summary: dict[str, list[str]] = {}
    for action in plan["actions"]:
        summary.setdefault(action["action"], []).append(action["relative"])
    execution = dict(config.get("execution") or {})
    schema_changes = []
    if "execution" not in config:
        schema_changes.append("config.json: an 'execution' section will be added (policy=auto)")
    if task_source and execution.get("task_source") != task_source:
        schema_changes.append(f"execution.task_source = {task_source}")
    blockers = active_session_blockers(project)
    report: dict[str, Any] = {
        "project": str(project), "from_version": current, "to_version": __version__,
        "needed": (_version_tuple(current) < _version_tuple(__version__) or bool(schema_changes)
                   or bool(legacy_renames)),
        "legacy_layout_renames": legacy_renames,
        "add": summary.get("create", []), "update": summary.get("managed-update", []),
        "merge": summary.get("merge-preserve-existing", []), "preserve_conflicts": summary.get("skip-user-owned", []),
        "schema_changes": schema_changes, "active_session_blockers": blockers,
        "rollback": "alpa upgrade --project <P> --rollback <backup-dir>",
        "command": f"alpa upgrade --project {project} --apply" + (f" --task-source {task_source}" if task_source else ""),
    }
    if not apply:
        report["status"] = "MIGRATION_READY" if not blockers else "MIGRATION_READY (once the active session closes)"
        report["applied"] = False
        return report
    if blockers:
        report.update(ok=False, applied=False, status="BLOCKED_ACTIVE_SESSION",
                      message="The project has an active Claude session, runner or recent activity; the upgrade was not applied.")
        return report
    if not report["needed"] and not task_source:
        report.update(ok=True, applied=False, status="UP_TO_DATE")
        return report
    before = _ledger_fingerprint(project)
    backup = make_backup(project)
    if legacy_renames:  # the backup above lives inside the legacy dir and moves with it
        legacy.migrate_layout(project)
        backup = project / STATE_DIR / backup.relative_to(project / legacy.LEGACY_STATE_DIR)
    result = install(project, profile_id, apply=True)
    cfg = read_json(project / STATE_DIR / "config.json", {})
    if task_source:
        cfg.setdefault("execution", {})["task_source"] = task_source
    cfg["upgraded_at"] = now_iso()
    atomic_json(project / STATE_DIR / "config.json", cfg)
    after = _ledger_fingerprint(project)
    if before != after:
        restored = globals()["rollback"](project, backup)
        report.update(ok=False, applied=False, status="ROLLED_BACK", restored=restored,
                      message="Task/approval history changed; restored from the backup.")
        return report
    history = read_json(project / STATE_DIR / "upgrades.json", {"schema": 1, "items": []})
    history["items"].append({"at": now_iso(), "from": current, "to": __version__, "backup": str(backup.relative_to(project)),
                             "conflicts": result.get("conflicts", []), "task_source": cfg.get("execution", {}).get("task_source")})
    atomic_json(project / STATE_DIR / "upgrades.json", history)
    report.update(ok=True, applied=True, status="MIGRATED", backup=str(backup.relative_to(project)),
                  conflicts=result.get("conflicts", []), validated=after)
    return report
