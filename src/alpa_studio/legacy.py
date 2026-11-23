"""Compatibility with installs made before the 0.4.0 rename (formerly "AI Game Studio", CLI `ags`).

Everything that still knows the old names lives here, so the rest of the package only speaks
the new ones: state dir `.alpa-studio`, launcher `scripts/alpa`, rule file `alpa-studio.md`,
environment variables `ALPA_*`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .util import atomic_json, read_json

STATE_DIR = ".alpa-studio"
LEGACY_STATE_DIR = ".ai-game-studio"
LEGACY_CLI = "ags"
# Legacy project-relative path -> new path. Applied to files on disk and to manifest keys.
LEGACY_FILE_RENAMES = {
    "scripts/ags": "scripts/alpa",
    ".claude/rules/ai-game-studio.md": ".claude/rules/alpa-studio.md",
}
# CLAUDE.md section written by `migrate` before 0.4.0; recognised so it is not added twice.
LEGACY_AUTHORITY_HEADING = "## AI Game Studio authority"
DEPRECATION_NOTICE = "alpa: the `ags` command is deprecated and will be removed; use `alpa` instead."


def env(name: str, default: str | None = None) -> str | None:
    """Read ALPA_<name>, falling back to the pre-0.4.0 AGS_<name>."""
    value = os.environ.get(f"ALPA_{name}")
    if value is None:
        value = os.environ.get(f"AGS_{name}")
    return default if value is None else value


def invoked_as_legacy(argv0: str | None = None) -> bool:
    argv0 = sys.argv[0] if argv0 is None else argv0
    return os.environ.get("ALPA_INVOKED_AS") == LEGACY_CLI or Path(argv0 or "").name == LEGACY_CLI


def warn_if_legacy_cli() -> None:
    if invoked_as_legacy():
        print(DEPRECATION_NOTICE, file=sys.stderr)


def has_legacy_layout(project: Path) -> bool:
    """True when only the pre-0.4.0 state dir exists (nothing has been migrated yet)."""
    return (project / LEGACY_STATE_DIR).is_dir() and not (project / STATE_DIR).exists()


def legacy_plan(project: Path) -> list[dict[str, str]]:
    """The renames migrate_layout() would perform, for dry-run reports."""
    if not has_legacy_layout(project):
        return []
    plan = [{"from": LEGACY_STATE_DIR, "to": STATE_DIR}]
    for old, new in LEGACY_FILE_RENAMES.items():
        if (project / old).is_file():
            action = "rename" if not (project / new).exists() else "keep (target exists)"
            plan.append({"from": old, "to": new, "action": action})
    return plan


def _rename_key(rel: str) -> str:
    if rel.startswith(LEGACY_STATE_DIR + "/"):
        return STATE_DIR + rel[len(LEGACY_STATE_DIR):]
    return LEGACY_FILE_RENAMES.get(rel, rel)


def migrate_layout(project: Path) -> dict[str, Any]:
    """Move a legacy layout to the new names. Callers take a backup first (see upgrade.py).

    Renamed managed files keep their manifest hash under the new name, so the following install
    updates them only when the user has not edited them (otherwise they are kept as conflicts).
    """
    if not has_legacy_layout(project):
        return {"migrated": False, "renamed": []}
    renamed = [f"{LEGACY_STATE_DIR} -> {STATE_DIR}"]
    os.replace(project / LEGACY_STATE_DIR, project / STATE_DIR)
    moved: dict[str, str] = {}
    for old, new in LEGACY_FILE_RENAMES.items():
        if (project / old).is_file() and not (project / new).exists():
            (project / new).parent.mkdir(parents=True, exist_ok=True)
            os.replace(project / old, project / new)
            moved[old] = new
            renamed.append(f"{old} -> {new}")
    manifest_path = project / STATE_DIR / "manifest.json"
    manifest = read_json(manifest_path, None)
    if isinstance(manifest, dict) and isinstance(manifest.get("files"), dict):
        files: dict[str, str] = {}
        for rel, digest in manifest["files"].items():
            new = _rename_key(rel)
            if new != rel and rel in LEGACY_FILE_RENAMES and rel not in moved:
                new = rel  # the file stayed where it was; keep tracking it there
            files[new] = digest
        manifest["files"] = files
        manifest["migrated_from_layout"] = LEGACY_STATE_DIR
        atomic_json(manifest_path, manifest)
    return {"migrated": True, "renamed": renamed}
