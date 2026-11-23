from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .doctor import health_report, inspect_project
from . import __version__
from .legacy import LEGACY_AUTHORITY_HEADING, LEGACY_STATE_DIR
from .util import (
    atomic_json, deep_merge_preserving_user, ensure_inside, now_iso, project_root,
    read_json, sha256, studio_root,
)

STATE_DIR = ".alpa-studio"
MANIFEST = f"{STATE_DIR}/manifest.json"


class StudioError(RuntimeError):
    pass


PROFILE_REQUIRED = {"id", "name", "summary", "required_roles", "required_evidence_types", "required_scenes"}


def _validate_profile(profile: Any, label: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise StudioError(f"Profile {label} is not a JSON object")
    missing = sorted(PROFILE_REQUIRED.difference(profile))
    if missing:
        raise StudioError(f"Profile {label} is missing required fields: {', '.join(missing)}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(profile["id"])):
        raise StudioError(f"Invalid profile id in {label}: {profile['id']}")
    return profile


def _profile(name: str, project: Path | None = None) -> dict[str, Any]:
    """Resolve a profile: a path to a JSON file, a built-in id (profiles/<id>.json), or the
    profile already stored in the project's config.json (so installs whose profile is not
    bundled with this release can still be upgraded)."""
    if name.endswith(".json") or "/" in name or os.sep in name:
        path = Path(name).expanduser()
        if not path.is_file():
            raise StudioError(f"Profile file not found: {name}")
        try:
            return _validate_profile(read_json(path), str(path))
        except json.JSONDecodeError as exc:
            raise StudioError(f"Profile file is not valid JSON: {name}: {exc}") from exc
    name = name.lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise StudioError(f"Invalid profile id: {name}")
    path = studio_root() / "profiles" / f"{name}.json"
    if not path.exists():
        stored = None
        for state in ((STATE_DIR, LEGACY_STATE_DIR) if project else ()):
            stored = (read_json(project / state / "config.json", {}) or {}).get("profile")
            if stored:
                break
        if isinstance(stored, dict) and stored.get("id") == name:
            return _validate_profile(stored, f"{name} (from {STATE_DIR}/config.json)")
        available = ", ".join(sorted(item.stem for item in path.parent.glob("*.json")))
        raise StudioError(f"Unknown profile: {name}. Available profiles: {available or 'none'}; "
                          "or pass the path to a profile JSON file")
    profile = _validate_profile(read_json(path), name)
    if profile["id"] != name:
        raise StudioError(f"Profile file/id mismatch: requested {name}, found {profile['id']}")
    return profile


def _template_files() -> list[Path]:
    root = studio_root() / "templates/project"
    return sorted(path for path in root.rglob("*") if path.is_file() and path.name != ".DS_Store")


def _payload_files() -> list[tuple[Path, Path]]:
    """Return project templates plus a complete project-local control-plane runtime."""
    root = studio_root()
    files: list[tuple[Path, Path]] = []
    template_root = root / "templates/project"
    for source in _template_files():
        files.append((source, source.relative_to(template_root)))
    for source_root, relative_root in [
        (root / "src", Path(STATE_DIR) / "runtime/src"),
        (root / "profiles", Path(STATE_DIR) / "runtime/profiles"),
        (root / "templates", Path(STATE_DIR) / "runtime/templates"),
    ]:
        for source in sorted(
            path for path in source_root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and path.name != ".DS_Store"
        ):
            files.append((source, relative_root / source.relative_to(source_root)))
    return files


def installation_plan(project: Path, profile_name: str) -> dict[str, Any]:
    profile = _profile(profile_name, project)
    info = inspect_project(project)
    if not info or not info["is_unity_project"]:
        raise StudioError("Target is not a Unity project (ProjectSettings/ProjectVersion.txt missing)")
    if not info["is_git_repo"]:
        raise StudioError("Target must be a Git repository so changes are reviewable and reversible")
    actions: list[dict[str, Any]] = []
    for source, rel in _payload_files():
        target = project / rel
        action = "create"
        if target.exists():
            if rel == Path(".claude/settings.json"):
                action = "merge-preserve-existing"
            elif (project / MANIFEST).exists() and str(rel) in read_json(project / MANIFEST, {}).get("files", {}):
                action = "managed-update"
            else:
                action = "skip-user-owned"
        actions.append({"source": str(source), "target": str(target), "relative": str(rel), "action": action})
    return {"project": str(project), "profile": profile["id"], "project_state": info, "actions": actions}


def _render(raw: bytes, profile: dict[str, Any]) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    replacements = {
        "{{PROFILE_ID}}": profile["id"], "{{PROFILE_NAME}}": profile["name"],
        "{{PROFILE_SUMMARY}}": profile["summary"], "{{FRAMEWORK_VERSION}}": __version__,
    }
    for old, new in replacements.items():
        text = text.replace(old, str(new))
    return text.encode("utf-8")


def install(project_arg: str | Path, profile_name: str, apply: bool = False) -> dict[str, Any]:
    project = project_root(project_arg)
    plan = installation_plan(project, profile_name)
    if not apply:
        return {**plan, "applied": False, "message": "Dry-run only; pass --apply to write."}
    if not plan["project_state"]["writable"]:
        raise StudioError("Target is not writable by the current user; --apply is blocked")
    profile = _profile(profile_name, project)
    previous = read_json(project / MANIFEST, {})
    previous_files = previous.get("files", {})
    written: dict[str, str] = {}
    conflicts: list[str] = []
    backup_root = project / STATE_DIR / "backups" / now_iso().replace(":", "-")

    for action in plan["actions"]:
        source = Path(action["source"])
        target = Path(action["target"])
        rel = action["relative"]
        ensure_inside(target, project)
        incoming = _render(source.read_bytes(), profile)
        if action["action"] == "skip-user-owned":
            conflicts.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel == ".claude/settings.json" and target.exists():
            existing = read_json(target, {})
            proposed = json.loads(incoming.decode("utf-8"))
            merged = deep_merge_preserving_user(existing, proposed)
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            atomic_json(target, merged)
        else:
            if target.exists():
                expected = previous_files.get(rel)
                if expected and sha256(target) != expected:
                    conflicts.append(rel)
                    continue
                backup = backup_root / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            tmp = target.with_name(f".{target.name}.alpa-tmp")
            tmp.write_bytes(incoming)
            os.replace(tmp, target)
            if target.suffix in {".sh", ".py"} or rel.startswith("scripts/") or "/hooks/" in str(target):
                target.chmod(target.stat().st_mode | 0o100)
        written[rel] = sha256(target)

    state = project / STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    for name, initial in {
        "approvals.json": {"schema": 1, "items": []},
        "tasks.json": {"schema": 1, "items": []},
        "events.json": {"schema": 1, "items": []},
        "qa.json": {"schema": 1, "reviews": []},
        "evidence.json": {"schema": 1, "sources": []},
        "certifications.json": {"schema": 1, "items": []},
    }.items():
        if not (state / name).exists():
            atomic_json(state / name, initial)
            written[f"{STATE_DIR}/{name}"] = sha256(state / name)
    from .session import DEFAULT_EXECUTION
    previous_config = read_json(state / "config.json", {}) or {}
    execution = {**DEFAULT_EXECUTION, **(profile.get("execution") or {}),
                 **(previous_config.get("execution") or {})}
    atomic_json(state / "config.json", {
        "schema": 1, "framework_version": __version__, "profile": profile, "execution": execution,
        "installed_at": now_iso(), "runtime": f"{STATE_DIR}/runtime",
        "source_repository": "https://github.com/alipasakaratas/AlpaTechGameStudio",
        "safety": {"paid_services_require_owner_approval": True, "publishing_requires_owner_approval": True},
    })
    written[f"{STATE_DIR}/config.json"] = sha256(state / "config.json")
    manifest = {
        "schema": 1, "framework": "Alpa Studio", "version": __version__, "profile": profile["id"],
        "installed_at": now_iso(), "files": written, "conflicts_skipped": conflicts,
        "backup": str(backup_root) if backup_root.exists() else None,
    }
    atomic_json(project / MANIFEST, manifest)
    return {**plan, "applied": True, "written": len(written), "conflicts": conflicts, "manifest": str(project / MANIFEST)}


def migration_plan(project_arg: str | Path, profile_name: str) -> dict[str, Any]:
    project = project_root(project_arg)
    base = installation_plan(project, profile_name)
    claude_root = project / ".claude"
    legacy_files = sorted(str(path.relative_to(project)) for path in claude_root.rglob("*") if path.is_file()) if claude_root.is_dir() else []
    settings = read_json(claude_root / "settings.json", {}) if (claude_root / "settings.json").exists() else {}
    runtime_refs = []
    manifest_path = project / "Packages/manifest.json"
    if manifest_path.exists():
        manifest_text = manifest_path.read_text(encoding="utf-8", errors="replace")
        runtime_refs = sorted(set(part.split('"')[0] for part in manifest_text.split('com.alpa.')[1:]))
        runtime_refs = [f"com.alpa.{name}" for name in runtime_refs]
    return {
        **base,
        "migration": {
            "replace_claude_control_plane": True,
            "legacy_claude_files": legacy_files,
            "legacy_enabled_plugins": settings.get("enabledPlugins", {}),
            "unity_runtime_dependencies_preserved": runtime_refs,
            "preserve_game_agents": True,
            "preserve_game_rules": True,
            "preserve_code_assets_docs": True,
        },
    }


def _patch_text(path: Path, replacements: dict[str, str], prepend_after_title: str | None = None) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in replacements.items():
        text = text.replace(old, new)
    if prepend_after_title and not any(h in text for h in ("## Alpa Studio authority", LEGACY_AUTHORITY_HEADING)):
        lines = text.splitlines(keepends=True)
        index = 1 if lines and lines[0].startswith("# ") else 0
        lines.insert(index, "\n" + prepend_after_title.strip() + "\n\n")
        text = "".join(lines)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def migrate(project_arg: str | Path, profile_name: str, apply: bool = False,
            replace_claude: bool = False) -> dict[str, Any]:
    """Replace a legacy Claude control plane while preserving product work and runtime packages."""
    project = project_root(project_arg)
    plan = migration_plan(project, profile_name)
    if not apply:
        return {**plan, "applied": False, "message": "Migration dry-run only; pass --apply --replace-claude."}
    if not replace_claude:
        raise StudioError("Migration apply requires --replace-claude to acknowledge the control-plane replacement")
    if not plan["project_state"]["writable"]:
        raise StudioError("Target is not writable by the current user; migration is blocked")

    stamp = now_iso().replace(":", "-")
    backup_root = project / STATE_DIR / "migration-backups" / stamp
    backup_root.mkdir(parents=True, exist_ok=False)
    rc_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(project), text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    rc_status = subprocess.run(["git", "status", "--porcelain"], cwd=str(project), text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    before = {"head": rc_head.stdout.strip(), "dirty_entries": len(rc_status.stdout.splitlines())}

    for rel in [Path("CLAUDE.md"), Path("scripts/run-backlog.sh"), Path("docs/BACKLOG.md")]:
        source = project / rel
        if source.exists():
            target = backup_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    old_claude = project / ".claude"
    saved_claude = backup_root / ".claude-original"
    if old_claude.exists():
        os.replace(old_claude, saved_claude)

    installed = install(project, profile_name, apply=True)
    preserved: list[str] = []
    if saved_claude.is_dir():
        for kind in ["agents", "rules"]:
            source_dir = saved_claude / kind
            if not source_dir.is_dir():
                continue
            for source in source_dir.rglob("*"):
                if not source.is_file():
                    continue
                target = project / ".claude" / kind / source.relative_to(source_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                preserved.append(str(target.relative_to(project)))

    authority = """## Alpa Studio authority

Alpa Studio is the only Claude orchestration and quality-control system for this project.
Use `/studio-start` for studio discovery/resume and `/next-task` for backlog work. The old
`alpa-studio` Claude plugin is disabled. Existing `com.alpa.*` Unity packages remain runtime
dependencies until they are deliberately migrated; their presence does not enable the old Claude workflow.
When the owner says one of the continue phrases in `.alpa-studio/config.json`
(`execution.continue_phrases`, default `start`, `continue`), invoke `/studio-start`, read persisted
state, and execute the first eligible queued task instead of only reporting status."""
    changed = []
    replacements = {"/alpa-studio:next-task": "/next-task"}
    if _patch_text(project / "CLAUDE.md", replacements, authority):
        changed.append("CLAUDE.md")
    if _patch_text(project / "docs/BACKLOG.md", replacements):
        changed.append("docs/BACKLOG.md")
    runner = project / "scripts/run-backlog.sh"
    if _patch_text(runner, {
        "/alpa-studio:next-task": "/next-task",
        "acceptEdits (default) | bypassPermissions (owner's choice, unattended runs)": "acceptEdits (default) | default; bypassPermissions is rejected",
    }):
        runner_text = runner.read_text(encoding="utf-8")
        guard = 'PERM="${CLAUDE_PERMISSION_MODE:-acceptEdits}"\n'
        if "Alpa Studio forbids bypassPermissions" not in runner_text and guard in runner_text:
            runner_text = runner_text.replace(
                guard,
                guard + 'if [ "$PERM" = "bypassPermissions" ]; then echo "Alpa Studio forbids bypassPermissions." >&2; exit 2; fi\n',
            )
            runner.write_text(runner_text, encoding="utf-8")
        changed.append("scripts/run-backlog.sh")

    studio_docs = project / "docs/studio"
    (studio_docs / "GAME-BIBLE.md").write_text(
        "# Game Bible authority\n\nCanonical existing document: [`../GDD.md`](../GDD.md). It is preserved; migration does not rewrite product history.\n",
        encoding="utf-8",
    )
    (studio_docs / "ART-BIBLE.md").write_text(
        "# Art Bible authority\n\nCanonical existing document: [`../ART-BIBLE.md`](../ART-BIBLE.md). Current approval markers in that document remain authoritative.\n",
        encoding="utf-8",
    )
    (studio_docs / "DECISIONS.md").write_text(
        "# Decision authority\n\nCanonical append-only history: [`../DECISION_LOG.md`](../DECISION_LOG.md). Migration does not rewrite or silently approve prior decisions.\n",
        encoding="utf-8",
    )
    (studio_docs / "STATUS.md").write_text(
        f"# Studio status\n\n- Profile: `{_profile(profile_name, project)['id']}`\n- Framework: `{__version__}`\n- Stage: migrated-existing-project\n- Certification: NOT CERTIFIED\n- Existing product work: PRESERVED\n- Legacy Claude plugin: DISABLED\n- Legacy Unity runtime packages: PRESERVED TEMPORARILY\n- Design authority reconciliation: PENDING OWNER REVIEW\n- Independent Visual QA: NOT RE-RUN AFTER MIGRATION\n- Device certification: NOT RUN AFTER MIGRATION\n",
        encoding="utf-8",
    )
    (studio_docs / "MIGRATION.md").write_text(
        "# Migration record\n\nThe legacy Claude control plane was replaced by Alpa Studio. Game code, assets, Git history, product documents, and Unity package dependencies were not deleted. Project-specific agents and rules were restored as Alpa Studio extensions. See `.alpa-studio/migration.json` for the machine-readable record.\n",
        encoding="utf-8",
    )
    game = _profile(profile_name, project)["name"]
    approval = approval_create(project, f"Reconcile current {game} design authority", "design-authority",
                               "Review existing GDD, Art Bible, target reference and decision log; lock only explicitly approved current decisions.")
    task = task_add(project, "Post-migration baseline audit",
                    f"Audit the preserved {game} project against Alpa Studio without changing gameplay or approved assets. Run tests, map open backlog, and report gaps.",
                    agent="studio-director")
    record = {
        "schema": 1, "framework_version": __version__, "profile": _profile(profile_name, project)["id"],
        "migrated_at": now_iso(), "backup": str(backup_root.relative_to(project)), "before": before,
        "legacy_claude_replaced": True, "game_files_deleted": False,
        "unity_runtime_dependencies_preserved": plan["migration"]["unity_runtime_dependencies_preserved"],
        "project_extensions_preserved": preserved, "patched_current_files": changed,
        "design_reconciliation_approval": approval["id"], "baseline_task": task["id"],
        "installer": {"written": installed["written"], "conflicts": installed["conflicts"]},
    }
    atomic_json(project / STATE_DIR / "migration.json", record)
    return {**plan, "applied": True, "migration_record": record}


def state_path(project: Path, name: str) -> Path:
    path = project / STATE_DIR / name
    ensure_inside(path, project)
    return path


def require_install(project: Path) -> dict[str, Any]:
    config = read_json(state_path(project, "config.json"))
    if not config:
        raise StudioError(f"Alpa Studio is not installed in {project}")
    return config


def approval_create(project: Path, title: str, category: str, details: str = "") -> dict[str, Any]:
    require_install(project)
    path = state_path(project, "approvals.json")
    data = read_json(path, {"schema": 1, "items": []})
    item = {"id": f"APR-{uuid.uuid4().hex[:8].upper()}", "title": title, "category": category,
            "details": details, "status": "pending", "created_at": now_iso(), "decided_at": None,
            "decision_note": None}
    data["items"].append(item)
    atomic_json(path, data)
    return item


def approval_decide(project: Path, approval_id: str, decision: str, note: str = "") -> dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise StudioError("Decision must be approved or rejected")
    path = state_path(project, "approvals.json")
    data = read_json(path, {"schema": 1, "items": []})
    for item in data["items"]:
        if item["id"] == approval_id:
            if item["status"] != "pending":
                raise StudioError("Approval has already been decided")
            item.update({"status": decision, "decided_at": now_iso(), "decision_note": note})
            atomic_json(path, data)
            return item
    raise StudioError(f"Approval not found: {approval_id}")


def task_add(project: Path, title: str, prompt: str, agent: str = "studio-director",
             requires_approval: str | None = None, depends_on: list[str] | None = None,
             required_gates: list[str] | None = None, acceptance: list[str] | None = None,
             priority: int = 0) -> dict[str, Any]:
    require_install(project)
    from .session import update_json
    path = state_path(project, "tasks.json")
    item = {"id": f"TASK-{uuid.uuid4().hex[:8].upper()}", "title": title, "prompt": prompt,
            "agent": agent, "status": "queued", "requires_approval": requires_approval,
            "attempts": 0, "created_at": now_iso(), "started_at": None, "completed_at": None,
            "last_error": None, "result_file": None, "depends_on": list(depends_on or []),
            "required_gates": list(required_gates or []), "acceptance": list(acceptance or []),
            "priority": int(priority), "session_ids": []}

    def mutate(data: dict[str, Any]) -> None:
        known = {existing["id"] for existing in data.setdefault("items", [])}
        unknown = [dep for dep in item["depends_on"] if dep not in known]
        if unknown:
            raise StudioError(f"Unknown dependency: {', '.join(unknown)}")
        data["items"].append(item)
    update_json(path, mutate, {"schema": 1, "items": []})
    return item


def _approval_is_granted(project: Path, approval_id: str | None) -> bool:
    if not approval_id:
        return True
    data = read_json(state_path(project, "approvals.json"), {"items": []})
    return any(item["id"] == approval_id and item["status"] == "approved" for item in data["items"])


def runner_once(project: Path, execute: bool = False, max_turns: int = 20) -> dict[str, Any]:
    """Single-task entry point kept for compatibility; `alpa run` is the autonomous loop."""
    from . import session
    require_install(project)
    cfg = session.execution_config(project)
    cfg["max_turns"] = max_turns
    buckets = session.classify(project, cfg)
    if not buckets["eligible"]:
        return {"status": "idle", "message": "No runnable queued task.",
                "reason": session._no_work_reason(buckets)}
    task = buckets["eligible"][0]
    if not execute:
        fake = {"attempt": int(task.get("attempts") or 0) + 1, "nonce": "dry-run"}
        return {"status": "dry-run", "task": task,
                "command": shlex.join(session.build_command(project, task, fake, cfg)),
                "session_policy": "One fresh Claude session per task; state persists on disk."}
    if not session.which_claude():
        raise StudioError("claude executable not found")
    try:
        session.acquire_runner_lock(project)
    except session.SessionError as exc:
        raise StudioError(str(exc)) from exc
    try:
        outcome = session.run_task(project, cfg, task["id"])
    finally:
        session.release_runner_lock(project)
    return {**outcome, "task": next(t for t in session.tasks(project, cfg) if t["id"] == task["id"])}


def evidence_add(project: Path, title: str, url: str, source_type: str, note: str = "") -> dict[str, Any]:
    if not url.startswith(("https://", "http://")):
        raise StudioError("Evidence requires a real http(s) source URL")
    path = state_path(project, "evidence.json")
    data = read_json(path, {"schema": 1, "sources": []})
    item = {"id": f"SRC-{uuid.uuid4().hex[:8].upper()}", "title": title, "url": url,
            "type": source_type, "note": note, "captured_at": now_iso(), "verified": False}
    data["sources"].append(item)
    atomic_json(path, data)
    return item


def checkpoint_create(project: Path, label: str) -> dict[str, Any]:
    require_install(project)
    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=str(project), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    item = {"id": f"CP-{uuid.uuid4().hex[:8].upper()}", "label": label, "created_at": now_iso(),
            "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
            "dirty": bool(git("status", "--porcelain")), "diff_stat": git("diff", "--stat")}
    path = state_path(project, "checkpoints.json")
    data = read_json(path, {"schema": 1, "items": []})
    data["items"].append(item)
    atomic_json(path, data)
    return item


def qa_score(project: Path, scores: dict[str, float], reviewer: str, stage: str) -> dict[str, Any]:
    weights = {"art_fidelity": 0.25, "composition": 0.15, "readability": 0.15,
               "interaction": 0.15, "performance": 0.15, "accessibility": 0.15}
    missing = [key for key in weights if key not in scores]
    if missing:
        raise StudioError(f"Missing QA scores: {', '.join(missing)}")
    if any(not 0 <= float(scores[key]) <= 100 for key in weights):
        raise StudioError("QA scores must be between 0 and 100")
    total = round(sum(float(scores[key]) * weight for key, weight in weights.items()), 2)
    review = {"id": f"QA-{uuid.uuid4().hex[:8].upper()}", "reviewer": reviewer, "stage": stage,
              "scores": scores, "weighted_score": total, "internal_target": 95,
              "passed": total >= 95, "created_at": now_iso(),
              "independence_note": "Reviewer identity is recorded; self-review must not be used for certification."}
    path = state_path(project, "qa.json")
    data = read_json(path, {"schema": 1, "reviews": []})
    data["reviews"].append(review)
    atomic_json(path, data)
    return review


def certification_status(project: Path) -> dict[str, Any]:
    config = require_install(project)
    health = health_report(project)
    qa = read_json(state_path(project, "qa.json"), {"reviews": []})["reviews"]
    evidence = read_json(state_path(project, "evidence.json"), {"sources": []})["sources"]
    pending = [item for item in read_json(state_path(project, "approvals.json"), {"items": []})["items"]
               if item["status"] == "pending"]
    requirements = {
        "core_health": health["core_ready"],
        "unity_project": bool(health["project"] and health["project"]["is_unity_project"]),
        "qa_95_independent": any(item["passed"] and item["reviewer"] not in {"developer", "studio-director"} for item in qa),
        "real_sources_recorded": len(evidence) >= 3,
        "no_pending_critical_approvals": not any(item["category"] in {"publish", "paid-service", "design-authority"} for item in pending),
        "android_test_capability": health["android"]["healthy"],
        "ios_test_capability": health["ios"]["healthy"],
    }
    dependency = config["profile"].get("depends_on_certification")
    if dependency:  # a profile may require another profile's certification first
        certified = read_json(state_path(project, "certifications.json"), {"items": []}).get("items", [])
        requirements[f"{dependency}_certified_first"] = any(
            item.get("profile") == dependency and item.get("certified") for item in certified)
    return {"profile": config["profile"]["id"], "certified": all(requirements.values()),
            "requirements": requirements, "note": "A missing capability is a failure, never an assumed pass."}

