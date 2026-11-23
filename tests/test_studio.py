from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from alpa_studio.dashboard import page, snapshot
from alpa_studio.doctor import health_report
from alpa_studio.project import (
    StudioError, approval_create, approval_decide, certification_status, checkpoint_create,
    evidence_add, install, installation_plan, migrate, migration_plan, qa_score, runner_once, task_add,
)


class StudioFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "Game"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.26f1\n")
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)

    def tearDown(self):
        self.temp.cleanup()

    def installed(self, profile="example"):
        return install(self.project, profile, apply=True)


class InstallTests(StudioFixture):
    def test_dry_run_writes_nothing(self):
        result = install(self.project, "example", apply=False)
        self.assertFalse(result["applied"])
        self.assertFalse((self.project / ".alpa-studio").exists())

    def test_requires_unity_project(self):
        (self.project / "ProjectSettings/ProjectVersion.txt").unlink()
        with self.assertRaises(StudioError):
            installation_plan(self.project, "example")

    def test_install_creates_isolated_layout(self):
        result = self.installed()
        self.assertTrue(result["applied"])
        self.assertTrue((self.project / ".claude/settings.json").exists())
        self.assertTrue((self.project / ".claude/hooks/studio_hook.py").exists())
        self.assertTrue((self.project / "docs/studio/ART-BIBLE.md").exists())
        self.assertTrue((self.project / ".alpa-studio/manifest.json").exists())

    def test_has_more_than_thirty_agents(self):
        self.installed()
        self.assertGreaterEqual(len(list((self.project / ".claude/agents").glob("*.md"))), 30)

    def test_every_agent_has_explicit_model_policy(self):
        self.installed()
        agents = list((self.project / ".claude/agents").glob("*.md"))
        self.assertTrue(agents)
        for agent in agents:
            self.assertRegex(agent.read_text(), r"(?m)^model: (opus|sonnet|haiku)$", agent.name)
        self.assertIn("model: opus", (self.project / ".claude/agents/studio-director.md").read_text())
        for role in ["game-designer", "concept-artist", "ui-ux-designer", "2d-artist", "3d-artist",
                     "animator", "audio-director", "accessibility"]:
            self.assertIn("model: opus", (self.project / f".claude/agents/{role}.md").read_text())
        self.assertIn("model: haiku", (self.project / ".claude/agents/continuity-manager.md").read_text())
        self.assertIn("model: opus", (self.project / ".claude/agents/unity-developer.md").read_text())
        self.assertIn("model: sonnet", (self.project / ".claude/agents/gameplay-qa.md").read_text())

    def test_project_local_launchers_and_start_trigger(self):
        self.installed()
        launcher = self.project / "scripts/alpa"
        start = self.project / "scripts/studio-start.sh"
        config = json.loads((self.project / ".alpa-studio/config.json").read_text())
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertTrue(os.access(start, os.X_OK))
        self.assertNotIn("studio_source", config)
        self.assertEqual(config["runtime"], ".alpa-studio/runtime")
        self.assertTrue((self.project / ".alpa-studio/runtime/src/alpa_studio/cli.py").exists())
        self.assertNotIn("studio_source", launcher.read_text())
        result = subprocess.run([str(launcher), "--help"], text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("execution.continue_phrases", (self.project / ".claude/rules/alpa-studio.md").read_text())
        self.assertIn("first eligible queued task", (self.project / ".claude/skills/studio-start/SKILL.md").read_text())

    def test_preserves_existing_settings(self):
        settings = self.project / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"enabledPlugins": {"existing@test": True}, "customKey": 7}))
        self.installed()
        merged = json.loads(settings.read_text())
        self.assertTrue(merged["enabledPlugins"]["existing@test"])
        self.assertEqual(merged["customKey"], 7)
        self.assertIn("hooks", merged)

    def test_existing_user_doc_is_skipped(self):
        doc = self.project / "docs/studio/ART-BIBLE.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("owner content")
        result = self.installed()
        self.assertIn("docs/studio/ART-BIBLE.md", result["conflicts"])
        self.assertEqual(doc.read_text(), "owner content")

    def test_profile_path(self):
        custom = Path(self.temp.name) / "custom-profile.json"
        data = json.loads((Path(__file__).parents[1] / "profiles/example.json").read_text())
        data["id"] = "custom-game"
        custom.write_text(json.dumps(data))
        self.installed(str(custom))
        config = json.loads((self.project / ".alpa-studio/config.json").read_text())
        self.assertEqual(config["profile"]["id"], "custom-game")

    def test_dynamic_profile_is_not_hardcoded_in_cli(self):
        result = subprocess.run(
            [str(Path(__file__).parents[1] / "bin/alpa"), "install", "--project", str(self.project),
             "--profile", "example"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["profile"], "example")
        self.assertFalse(plan["applied"])

    def test_unknown_profile_has_actionable_error(self):
        with self.assertRaisesRegex(StudioError, "Available profiles"):
            installation_plan(self.project, "not-a-real-profile")


class WorkflowTests(StudioFixture):
    def setUp(self):
        super().setUp()
        self.installed()

    def test_approval_lifecycle(self):
        item = approval_create(self.project, "Approve Art Bible", "design-authority")
        decided = approval_decide(self.project, item["id"], "approved", "owner chose C")
        self.assertEqual(decided["status"], "approved")
        with self.assertRaises(StudioError):
            approval_decide(self.project, item["id"], "approved")

    def test_task_waits_for_approval(self):
        approval = approval_create(self.project, "Paid service", "paid-service")
        task_add(self.project, "Generate", "Generate assets", requires_approval=approval["id"])
        result = runner_once(self.project, execute=False)
        self.assertEqual(result["status"], "idle")
        approval_decide(self.project, approval["id"], "approved")
        result = runner_once(self.project, execute=False)
        self.assertEqual(result["status"], "dry-run")

    def test_runner_is_fresh_bounded_session(self):
        task_add(self.project, "Audit", "Audit current project")
        result = runner_once(self.project, execute=False, max_turns=12)
        self.assertIn("claude -p", result["command"])
        self.assertIn("--max-turns 12", result["command"])
        self.assertNotIn("dangerously", result["command"])

    def test_evidence_requires_real_url(self):
        with self.assertRaises(StudioError):
            evidence_add(self.project, "Claim", "not-a-url", "review")
        item = evidence_add(self.project, "Store page", "https://example.com/game", "competitor")
        self.assertFalse(item["verified"])

    def test_qa_weight_and_target(self):
        scores = {"art_fidelity": 98, "composition": 96, "readability": 97,
                  "interaction": 96, "performance": 94, "accessibility": 95}
        review = qa_score(self.project, scores, "visual-qa", "scene")
        self.assertTrue(review["passed"])
        self.assertGreaterEqual(review["weighted_score"], 95)

    def test_qa_rejects_missing_dimensions(self):
        with self.assertRaises(StudioError):
            qa_score(self.project, {"art_fidelity": 100}, "visual-qa", "scene")

    def test_checkpoint_is_non_destructive(self):
        item = checkpoint_create(self.project, "before work")
        self.assertIn("head", item)
        self.assertTrue((self.project / ".alpa-studio/checkpoints.json").exists())

    def test_certification_is_honestly_false_without_evidence(self):
        status = certification_status(self.project)
        self.assertFalse(status["certified"])
        self.assertFalse(status["requirements"]["qa_95_independent"])


class MigrationTests(StudioFixture):
    def setUp(self):
        super().setUp()
        (self.project / ".claude/agents").mkdir(parents=True)
        (self.project / ".claude/rules").mkdir(parents=True)
        (self.project / ".claude/settings.json").write_text(json.dumps({
            "enabledPlugins": {"alpa-studio@alpa-studio-local": True}
        }))
        (self.project / ".claude/agents/level-designer.md").write_text(
            "---\nname: level-designer\ndescription: Project-specific level design.\n---\nlegacy project rules\n"
        )
        (self.project / ".claude/agents/economy-tuner.md").write_text(
            "---\nname: economy-tuner\ndescription: Project economy.\n---\nlegacy economy rules\n"
        )
        (self.project / ".claude/rules/core-purity.md").write_text("# Core purity\n")
        (self.project / "CLAUDE.md").write_text("# My Game\n\nDaily: `/alpa-studio:next-task`.\n")
        (self.project / "docs").mkdir()
        (self.project / "docs/BACKLOG.md").write_text("Use `/alpa-studio:next-task`.\n")
        (self.project / "scripts").mkdir()
        (self.project / "scripts/run-backlog.sh").write_text(
            '#!/bin/sh\nPERM="${CLAUDE_PERMISSION_MODE:-acceptEdits}"\n'
            '# acceptEdits (default) | bypassPermissions (owner\'s choice, unattended runs)\n'
            'claude -p "/alpa-studio:next-task M-001"\n'
        )
        (self.project / "Packages").mkdir()
        (self.project / "Packages/manifest.json").write_text(
            '{"dependencies":{"com.alpa.services":"file:../../alpa-studio/Packages/com.alpa.services"}}\n'
        )

    def test_migration_dry_run_is_non_mutating(self):
        before = (self.project / ".claude/settings.json").read_text()
        result = migrate(self.project, "example", apply=False)
        self.assertFalse(result["applied"])
        self.assertEqual((self.project / ".claude/settings.json").read_text(), before)
        self.assertIn("alpa-studio@alpa-studio-local", result["migration"]["legacy_enabled_plugins"])

    def test_migration_replaces_plugin_and_preserves_project_extensions(self):
        result = migrate(self.project, "example", apply=True, replace_claude=True)
        self.assertTrue(result["applied"])
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        self.assertNotIn("enabledPlugins", settings)
        self.assertIn("hooks", settings)
        self.assertIn("legacy project rules", (self.project / ".claude/agents/level-designer.md").read_text())
        self.assertTrue((self.project / ".claude/agents/economy-tuner.md").exists())
        self.assertTrue((self.project / ".claude/rules/core-purity.md").exists())
        self.assertIn("/next-task", (self.project / "CLAUDE.md").read_text())
        self.assertIn("Alpa Studio authority", (self.project / "CLAUDE.md").read_text())
        runner = (self.project / "scripts/run-backlog.sh").read_text()
        self.assertIn("/next-task", runner)
        self.assertIn("forbids bypassPermissions", runner)
        self.assertTrue((self.project / ".alpa-studio/migration.json").exists())
        backup = self.project / result["migration_record"]["backup"]
        self.assertTrue((backup / ".claude-original/settings.json").exists())
        self.assertIn("com.alpa.services", result["migration_record"]["unity_runtime_dependencies_preserved"])
        self.assertTrue((self.project / ".claude/skills/next-task/SKILL.md").exists())


class HookTests(StudioFixture):
    def setUp(self):
        super().setUp()
        self.installed()
        self.hook = self.project / ".claude/hooks/studio_hook.py"

    def call_hook(self, payload):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project)}
        return subprocess.run(["python3", str(self.hook)], input=json.dumps(payload), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)

    def test_blocks_destructive_command(self):
        result = self.call_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                 "tool_input": {"command": "git reset --hard HEAD"}})
        self.assertEqual(result.returncode, 2)

    def test_blocks_publish_without_approval(self):
        result = self.call_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                 "tool_input": {"command": "fastlane deliver"}})
        self.assertEqual(result.returncode, 2)

    def test_allows_safe_command(self):
        result = self.call_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                 "tool_input": {"command": "git status --short"}})
        self.assertEqual(result.returncode, 0)

    def test_blocks_secret_file_access_from_bash(self):
        result = self.call_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                 "tool_input": {"command": "cat .env"}})
        self.assertEqual(result.returncode, 2)

    def test_publish_can_be_owner_approved(self):
        item = approval_create(self.project, "Release candidate upload", "publish")
        approval_decide(self.project, item["id"], "approved")
        result = self.call_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                 "tool_input": {"command": "fastlane deliver"}})
        self.assertEqual(result.returncode, 0)

    def test_protected_decision_is_blocked(self):
        locks = self.project / ".alpa-studio/locks.json"
        locks.write_text(json.dumps({"paths": ["docs/studio/ART-BIBLE.md"]}))
        result = self.call_hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                                 "tool_input": {"file_path": str(self.project / "docs/studio/ART-BIBLE.md")}})
        self.assertEqual(result.returncode, 2)


class DashboardAndHealthTests(StudioFixture):
    def setUp(self):
        super().setUp()
        self.installed()

    def test_dashboard_page_and_snapshot(self):
        approval_create(self.project, "Approve concept", "design-authority")
        asset = self.project / "docs/studio/assets/concept-a.png"
        asset.write_bytes(b"not-a-real-png-but-valid-gallery-fixture")
        content = page(self.project, "token").decode()
        self.assertIn("Mission", content)
        self.assertIn("Approve concept", content)
        self.assertIn("concept-a.png", content)
        data = snapshot(self.project)
        self.assertEqual(data["config"]["profile"]["id"], "example")
        self.assertEqual(data["assets"][0]["name"], "concept-a.png")

    def test_doctor_has_truthful_capability_fields(self):
        report = health_report(self.project)
        self.assertIn(report["status"], {"ready", "degraded"})
        self.assertIn("healthy", report["ios"])
        self.assertIn("reason", report["android"])
        self.assertTrue(report["project"]["is_unity_project"])


if __name__ == "__main__":
    unittest.main()

