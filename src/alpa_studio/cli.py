from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .dashboard import serve
from .doctor import health_report
from .project import (
    StudioError, approval_create, approval_decide, certification_status, checkpoint_create,
    evidence_add, install, migrate, qa_score, runner_once, state_path, task_add,
)
from . import legacy, session
from .upgrade import upgrade
from .util import project_root, read_json


def emit(value: object, human: bool = False) -> None:
    if human and isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="alpa", description="Alpa Studio local-first control plane")
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="Truthful tool, device, storage and project health")
    p.add_argument("--project")

    p = sub.add_parser("install", help="Install an isolated project copy (dry-run by default)")
    p.add_argument("--project", required=True)
    p.add_argument("--profile", required=True, metavar="PROFILE", help="Profile id (profiles/<id>.json) or path to a profile JSON file")
    p.add_argument("--apply", action="store_true", help="Write after all preflight checks pass")

    p = sub.add_parser("migrate", help="Replace a legacy Claude control plane while preserving product work")
    p.add_argument("--project", required=True)
    p.add_argument("--profile", required=True, metavar="PROFILE", help="Profile id (profiles/<id>.json) or path to a profile JSON file")
    p.add_argument("--apply", action="store_true", help="Apply the reviewed migration plan")
    p.add_argument("--replace-claude", action="store_true", help="Acknowledge replacement of the project .claude control plane")

    p = sub.add_parser("approval", help="Manage owner approval queue")
    p.add_argument("action", choices=["create", "list", "approve", "reject"])
    p.add_argument("--project")
    p.add_argument("--id")
    p.add_argument("--title")
    p.add_argument("--category", choices=["design-authority", "paid-service", "publish", "mechanic", "privacy", "other"], default="other")
    p.add_argument("--details", default="")
    p.add_argument("--note", default="")

    p = sub.add_parser("task", help="Persistent task queue and per-task session records")
    p.add_argument("action", choices=["add", "list", "start", "finish", "progress", "show", "retry"])
    p.add_argument("--project")
    p.add_argument("--id")
    p.add_argument("--title")
    p.add_argument("--prompt")
    p.add_argument("--agent", default="studio-director")
    p.add_argument("--requires-approval")
    p.add_argument("--depends-on", action="append", default=[], help="add: task id this task depends on")
    p.add_argument("--gate", action="append", default=[], help="add: required gate (substring of a passed test cmd)")
    p.add_argument("--acceptance", action="append", default=[], help="add: acceptance criterion")
    p.add_argument("--priority", type=int, default=0)
    p.add_argument("--status", choices=list(session.FINISH_STATUSES))
    p.add_argument("--summary", default="")
    p.add_argument("--evidence", action="append", default=[])
    p.add_argument("--test", action="append", default=[], help='"cmd=...;result=passed|failed|unverified"')
    p.add_argument("--next", dest="next_actions", action="append", default=[], help="finish/progress: next action")
    p.add_argument("--approval-title")
    p.add_argument("--phase", default="")
    p.add_argument("--note", default="")
    p.add_argument("--subtask", action="append", default=[])
    p.add_argument("--tests-status", default="")
    p.add_argument("--reason", default="owner-approved retry")

    p = sub.add_parser("run", help="Autonomous loop: one fresh Claude process per task (default mode)")
    p.add_argument("--project")
    p.add_argument("--max-tasks", type=int)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-turns", type=int)
    p.add_argument("--model")
    p.add_argument("--permission-mode", choices=["acceptEdits", "default", "plan", "auto", "dontAsk"])
    p.add_argument("--json", action="store_true", help="Machine-readable output")
    p.add_argument("--auto", action="store_true", help="Explicit auto mode (the default)")

    p = sub.add_parser("resume", help="Clear pause and continue the autonomous loop")
    p.add_argument("--project")
    p.add_argument("--no-run", action="store_true")
    p.add_argument("--max-tasks", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("pause", help="Stop after the current task finishes")
    p.add_argument("--project")
    p.add_argument("--reason", default="")
    p = sub.add_parser("status", help="Runner, current task, approvals and dependency status")
    p.add_argument("--project")
    p = sub.add_parser("next", help="Show the next eligible task (manual continue fallback)")
    p.add_argument("--project")
    p = sub.add_parser("context", help="Print the bounded SessionStart context")
    p.add_argument("--project")
    p.add_argument("--source", default="startup")

    p = sub.add_parser("upgrade", help="Versioned framework upgrade of an installed project (dry-run by default)")
    p.add_argument("--project", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--task-source", choices=["ledger", "backlog"])
    p.add_argument("--rollback", metavar="BACKUP_DIR")

    p = sub.add_parser("runner", help="Run the next eligible task in a fresh Claude session")
    p.add_argument("--project")
    p.add_argument("--execute", action="store_true", help="Actually start Claude; default only shows command")
    p.add_argument("--max-turns", type=int, default=20)

    p = sub.add_parser("evidence", help="Record source-backed market/video/review evidence")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("--project")
    p.add_argument("--title")
    p.add_argument("--url")
    p.add_argument("--type", choices=["competitor", "video", "review", "policy", "research"], default="research")
    p.add_argument("--note", default="")

    p = sub.add_parser("checkpoint", help="Record a reversible Git checkpoint ledger entry")
    p.add_argument("action", choices=["create", "list"])
    p.add_argument("--project")
    p.add_argument("--label", default="manual checkpoint")

    p = sub.add_parser("qa", help="Record a weighted independent visual QA review")
    p.add_argument("--project")
    p.add_argument("--reviewer", required=True)
    p.add_argument("--stage", required=True)
    for key in ["art-fidelity", "composition", "readability", "interaction", "performance", "accessibility"]:
        p.add_argument(f"--{key}", type=float, required=True)

    p = sub.add_parser("certify", help="Evaluate certification gates without pretending unavailable checks passed")
    p.add_argument("--project")

    p = sub.add_parser("dashboard", help="Run local Mission Control")
    p.add_argument("--project")
    p.add_argument("--port", type=int, default=8765)
    return root


def need(value: str | None, name: str) -> str:
    if not value:
        raise StudioError(f"{name} is required for this action")
    return value


def _migrate_legacy_layout(project: Path) -> int | None:
    """Commands that find only a pre-0.4.0 `.ai-game-studio` dir migrate it first, through the same
    backed-up, rollback-able path as `alpa upgrade --apply`. Returns an exit code when blocked."""
    if not legacy.has_legacy_layout(project):
        return None
    result = upgrade(project, apply=True)
    if not result.get("ok", True) or not result.get("applied", True):
        print(f"alpa: found legacy {legacy.LEGACY_STATE_DIR}/ but could not migrate it "
              f"({result.get('status')}); run `alpa upgrade --project {project}` for details.", file=sys.stderr)
        return 3
    print(f"alpa: migrated {legacy.LEGACY_STATE_DIR}/ to {legacy.STATE_DIR}/ "
          f"(backup: {result.get('backup')}).", file=sys.stderr)
    return None


def main(argv: list[str] | None = None) -> int:
    legacy.warn_if_legacy_cli()
    args = parser().parse_args(argv)
    try:
        if args.command in ("install", "migrate") and legacy.has_legacy_layout(Path(args.project).expanduser()):
            raise StudioError(f"{args.project} has a pre-0.4.0 {legacy.LEGACY_STATE_DIR}/ install; "
                              f"run `alpa upgrade --project {args.project} --apply` instead.")
        if args.command == "doctor":
            emit(health_report(project_root(args.project) if args.project else None)); return 0
        if args.command == "install":
            emit(install(args.project, args.profile, args.apply)); return 0
        if args.command == "migrate":
            emit(migrate(args.project, args.profile, args.apply, args.replace_claude)); return 0
        if args.command == "upgrade":
            result = upgrade(args.project, apply=args.apply, task_source=args.task_source,
                             rollback=args.rollback)
            emit(result); return 0 if result.get("ok", True) else 3
        project = project_root(args.project or legacy.env("PROJECT") or os.getcwd())
        blocked = _migrate_legacy_layout(project)
        if blocked is not None:
            return blocked
        if args.command in ("run", "resume"):
            if args.command == "resume":
                session.resume(project)
                if args.no_run:
                    print("Pause cleared."); return 0
            overrides = {} if args.command == "resume" else {
                "max_turns": args.max_turns, "model": args.model, "permission_mode": args.permission_mode}
            result = session.run(project, max_tasks=args.max_tasks,
                                 dry_run=getattr(args, "dry_run", False), overrides=overrides)
            if args.json: emit(result)
            else: print(session.summarize(result))
            return result["exit_code"]
        if args.command == "pause":
            emit(session.pause(project, args.reason)); return 0
        if args.command == "status":
            emit(session.status(project)); return 0
        if args.command == "context":
            print(session.session_context(project, args.source)); return 0
        if args.command == "next":
            buckets = session.classify(project)
            if not buckets["eligible"]:
                print("No eligible task: " + session._no_work_reason(buckets)); return 1
            task = buckets["eligible"][0]
            emit({"id": task["id"], "title": task.get("title"), "prompt": task.get("prompt")}); return 0
        if args.command == "approval":
            if args.action == "create":
                emit(approval_create(project, need(args.title, "--title"), args.category, args.details))
            elif args.action == "list":
                emit(read_json(state_path(project, "approvals.json"), {"items": []}))
            else:
                emit(approval_decide(project, need(args.id, "--id"), "approved" if args.action == "approve" else "rejected", args.note))
        elif args.command == "task":
            if args.action == "add":
                emit(task_add(project, need(args.title, "--title"), need(args.prompt, "--prompt"), args.agent,
                              args.requires_approval, depends_on=args.depends_on, required_gates=args.gate,
                              acceptance=args.acceptance, priority=args.priority))
            elif args.action == "start":
                emit(session.start_task(project, args.id, mode="manual"))  # no --id: next eligible
            elif args.action == "finish":
                emit(session.finish_task(project, need(args.id, "--id"), need(args.status, "--status"),
                                         need(args.summary, "--summary"), args.evidence, args.test,
                                         args.next_actions, args.approval_title))
            elif args.action == "progress":
                emit(session.progress(project, need(args.id, "--id"), need(args.phase, "--phase"), args.note,
                                      " ".join(args.next_actions), args.subtask, args.tests_status))
            elif args.action == "retry":
                emit(session.retry_task(project, need(args.id, "--id"), args.reason))
            elif args.action == "show":
                emit({"result": session.result_for(project, need(args.id, "--id")),
                      "progress": session.latest_progress(project, args.id)})
            else:
                emit(read_json(state_path(project, "tasks.json"), {"items": []}))
        elif args.command == "runner":
            emit(runner_once(project, args.execute, args.max_turns))
        elif args.command == "evidence":
            if args.action == "add":
                emit(evidence_add(project, need(args.title, "--title"), need(args.url, "--url"), args.type, args.note))
            else:
                emit(read_json(state_path(project, "evidence.json"), {"sources": []}))
        elif args.command == "checkpoint":
            if args.action == "create": emit(checkpoint_create(project, args.label))
            else: emit(read_json(state_path(project, "checkpoints.json"), {"items": []}))
        elif args.command == "qa":
            scores = {"art_fidelity": args.art_fidelity, "composition": args.composition,
                      "readability": args.readability, "interaction": args.interaction,
                      "performance": args.performance, "accessibility": args.accessibility}
            emit(qa_score(project, scores, args.reviewer, args.stage))
        elif args.command == "certify":
            result = certification_status(project); emit(result); return 0 if result["certified"] else 3
        elif args.command == "dashboard":
            serve(project, args.port)
        return 0
    except (StudioError, session.SessionError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

