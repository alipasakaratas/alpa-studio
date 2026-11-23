"""Pre-0.4.0 compatibility: legacy layout migration, the `ags` alias, AGS_* env fallback."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alpa_studio import legacy, session
from alpa_studio.cli import main
from alpa_studio.project import install
from alpa_studio.upgrade import rollback, upgrade

REPO = Path(__file__).parents[1]


def make_legacy_layout(project: Path) -> None:
    """Install the current template, then rewind names to the pre-0.4.0 layout."""
    install(project, "example", apply=True)
    os.replace(project / ".alpa-studio", project / ".ai-game-studio")
    os.replace(project / "scripts/alpa", project / "scripts/ags")
    os.replace(project / ".claude/rules/alpa-studio.md", project / ".claude/rules/ai-game-studio.md")
    manifest_path = project / ".ai-game-studio/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    reverse = {new: old for old, new in legacy.LEGACY_FILE_RENAMES.items()}
    files = {}
    for rel, digest in manifest["files"].items():
        if rel.startswith(".alpa-studio/"):
            rel = ".ai-game-studio/" + rel[len(".alpa-studio/"):]
        files[reverse.get(rel, rel)] = digest
    manifest["files"] = files
    manifest_path.write_text(json.dumps(manifest))
    tasks = project / ".ai-game-studio/tasks.json"
    tasks.write_text(json.dumps({"schema": 1, "items": [{"id": "OLD-1", "title": "Old task", "status": "done"}]}))


class LegacyFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "Game"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.26f1\n")
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        make_legacy_layout(self.project)
        patcher = mock.patch("alpa_studio.upgrade.active_session_blockers", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()


class LayoutMigrationTests(LegacyFixture):
    def test_dry_run_lists_renames_and_changes_nothing(self):
        report = upgrade(self.project, apply=False)
        self.assertTrue(report["needed"])
        moves = {(r["from"], r["to"]) for r in report["legacy_layout_renames"]}
        self.assertIn((".ai-game-studio", ".alpa-studio"), moves)
        self.assertIn(("scripts/ags", "scripts/alpa"), moves)
        self.assertTrue((self.project / ".ai-game-studio").is_dir())
        self.assertFalse((self.project / ".alpa-studio").exists())

    def test_apply_renames_dir_files_and_manifest_keys_with_backup(self):
        report = upgrade(self.project, apply=True)
        self.assertEqual(report["status"], "MIGRATED", report)
        self.assertFalse((self.project / ".ai-game-studio").exists())
        self.assertTrue((self.project / "scripts/alpa").is_file())
        self.assertTrue((self.project / ".claude/rules/alpa-studio.md").is_file())
        self.assertFalse((self.project / ".claude/rules/ai-game-studio.md").exists())
        manifest = json.loads((self.project / ".alpa-studio/manifest.json").read_text())
        self.assertFalse([k for k in manifest["files"] if "ai-game-studio" in k])
        self.assertIn("scripts/alpa", manifest["files"])
        tasks = json.loads((self.project / ".alpa-studio/tasks.json").read_text())
        self.assertEqual(tasks["items"][0]["id"], "OLD-1")  # ledger survives the move
        backup = self.project / report["backup"]
        self.assertTrue((backup / "manifest.json").is_file())
        self.assertTrue(report["backup"].startswith(".alpa-studio/upgrade-backups/"))

    def test_rollback_restores_legacy_files(self):
        report = upgrade(self.project, apply=True)
        result = rollback(self.project, self.project / report["backup"])
        self.assertTrue(result["ok"])
        self.assertTrue((self.project / "scripts/ags").is_file())
        self.assertTrue((self.project / ".ai-game-studio/tasks.json").is_file())

    def test_any_project_command_migrates_legacy_layout_first(self):
        with mock.patch("sys.stderr") as err:
            code = main(["status", "--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertTrue((self.project / ".alpa-studio/config.json").is_file())
        self.assertFalse((self.project / ".ai-game-studio").exists())
        self.assertIn("migrated", "".join(c.args[0] for c in err.write.call_args_list))


class AliasAndEnvTests(unittest.TestCase):
    def test_ags_alias_prints_one_deprecation_line_and_works(self):
        result = subprocess.run([str(REPO / "bin/ags"), "--help"], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), legacy.DEPRECATION_NOTICE)
        self.assertIn("usage", result.stdout.lower())

    def test_alpa_prints_no_deprecation_notice(self):
        env = {k: v for k, v in os.environ.items() if k != "ALPA_INVOKED_AS"}
        result = subprocess.run([str(REPO / "bin/alpa"), "--help"], text=True, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("deprecated", result.stderr)

    def test_env_prefers_alpa_and_falls_back_to_ags(self):
        with mock.patch.dict(os.environ, {"AGS_X_TEST": "old"}, clear=False):
            self.assertEqual(legacy.env("X_TEST"), "old")
            with mock.patch.dict(os.environ, {"ALPA_X_TEST": "new"}):
                self.assertEqual(legacy.env("X_TEST"), "new")
        self.assertEqual(legacy.env("X_TEST_MISSING", "d"), "d")


class ContinuePhraseTests(unittest.TestCase):
    def test_default_and_configured_phrases(self):
        self.assertEqual(session.continue_phrases({}), ["start", "continue"])
        self.assertEqual(session.continue_phrases({"continue_phrases": "go"}), ["go"])
        self.assertEqual(session.continue_phrases({"continue_phrases": ["  ", "weiter"]}), ["weiter"])
        self.assertEqual(session.continue_phrases({"continue_phrases": []}), ["start", "continue"])


if __name__ == "__main__":
    unittest.main()
