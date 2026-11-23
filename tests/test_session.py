"""Context & session management: orchestrator, gates, hooks, recovery, upgrade (hermetic).

A fake `claude` binary (ALPA_CLAUDE_BIN) behaves like a headless Claude session: it runs the
project's SessionStart hook, records the task through the project-local `scripts/alpa`, then runs
the Stop hook, and prints the `--output-format json` result. Behaviour is selected by tokens in
the task prompt: [noresult] [usage] [crash] [approval] [trystart].
An opt-in REAL test (ALPA_REAL_CLAUDE=1) drives the actual Claude Code CLI.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path
from unittest import mock

from alpa_studio import session
from alpa_studio.project import approval_create, approval_decide, install, task_add
from alpa_studio.upgrade import upgrade

FAKE_CLAUDE = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import json, os, re, subprocess, sys, uuid
    from pathlib import Path
    argv = sys.argv[1:]
    prompt = argv[argv.index("-p") + 1]
    root = Path.cwd()
    sid = str(uuid.uuid4())
    task = re.search(r"Task: (\S+) \(attempt", prompt).group(1)
    log = Path(os.environ["FAKE_LOG"]); log.mkdir(parents=True, exist_ok=True)
    hook = [sys.executable, str(root / ".claude/hooks/studio_hook.py")]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    def call(payload):
        p = subprocess.run(hook, input=json.dumps(payload), text=True, capture_output=True, env=env)
        return {"code": p.returncode, "out": p.stdout, "err": p.stderr}
    start = call({"hook_event_name": "SessionStart", "session_id": sid, "source": "startup", "cwd": str(root)})
    rec = {"task": task, "session_id": sid, "argv": argv, "start": start}
    if "[usage]" in prompt:
        print("Claude AI usage limit reached|resets at 5pm"); sys.exit(1)
    if "[crash]" in prompt:
        print("Segmentation fault"); sys.exit(1)
    if "[trystart]" in prompt:
        rec["pretool"] = call({"hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Bash",
                               "tool_input": {"command": "scripts/alpa task start"}})
    if "[noresult]" not in prompt:
        status = ("blocked" if "[permission]" in prompt else
                  "waiting_for_approval" if "[approval]" in prompt else "done")
        fin = subprocess.run([str(root / "scripts/alpa"), "task", "finish", "--id", task, "--status", status,
                              "--summary", f"{task} done", "--evidence", "tests/fake.txt",
                              "--test", "cmd=unit;result=passed", "--next", "next"],
                             text=True, capture_output=True)
        rec["finish"] = {"code": fin.returncode, "out": fin.stdout[-500:], "err": fin.stderr[-500:]}
    rec["stop"] = call({"hook_event_name": "Stop", "session_id": sid, "stop_hook_active": False})
    (log / f"{sid}.json").write_text(json.dumps(rec, ensure_ascii=False))
    result = {"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
              "total_cost_usd": 0}
    if "[permission]" in prompt:
        result["permission_denials"] = [{"tool_name": "Bash", "tool_input": {"command": "scripts/run-tests.sh EditMode"}}]
    print(json.dumps(result))
''').lstrip()


class SessionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project = base / "Game"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.26f1\n")
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        install(self.project, "example", apply=True)
        self.fake = base / "bin/claude"
        self.fake.parent.mkdir()
        self.fake.write_text(FAKE_CLAUDE.replace("/usr/bin/env python3", sys.executable, 1))
        self.fake.chmod(0o755)
        self.log = base / "fake-log"
        self.env = mock.patch.dict(os.environ, {"ALPA_CLAUDE_BIN": str(self.fake), "FAKE_LOG": str(self.log),
                                                "ALPA_BACKOFF_SECONDS": "0"})
        self.env.start()
        for key in ("ALPA_TASK_ID", "ALPA_TASK_NONCE", "ALPA_RUN_MODE"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def add(self, title, **kw):
        return task_add(self.project, title, kw.pop("prompt", title), **kw)["id"]

    def task(self, task_id):
        return next(t for t in session.tasks(self.project) if t["id"] == task_id)

    def sessions(self):
        return [json.loads(p.read_text()) for p in sorted(self.log.glob("*.json"))] if self.log.exists() else []

    def run_loop(self, **kw):
        return session.run(self.project, sleep=lambda s: None, **kw)

    def hook(self, payload, **env):
        merged = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), **env}
        return subprocess.run([sys.executable, str(self.project / ".claude/hooks/studio_hook.py")],
                              input=json.dumps(payload), text=True, capture_output=True, env=merged)


class AutoModeTests(SessionFixture):
    def test_new_install_defaults_to_auto_mode(self):
        cfg = json.loads((self.project / ".alpa-studio/config.json").read_text())
        self.assertEqual(cfg["execution"]["policy"], "auto")
        self.assertIn('alpa" run', (self.project / "scripts/studio-start.sh").read_text())

    def test_three_tasks_three_distinct_sessions_no_intervention(self):
        ids = [self.add(f"Task {n}") for n in range(3)]
        result = self.run_loop()
        self.assertEqual(result["stop_reason"], "no_eligible", result)
        self.assertEqual(result["exit_code"], session.EXIT_OK)
        self.assertEqual([r["task_id"] for r in result["runs"]], ids)
        sids = [r["session_id"] for r in result["runs"]]
        self.assertEqual(len(set(sids)), 3)
        for task_id, sid in zip(ids, sids):
            task = self.task(task_id)
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["session_ids"], [sid])
            record = session.result_for(self.project, task_id)
            self.assertEqual(record["session_id"], sid)  # SessionStart hook claimed the marker
        for rec in self.sessions():
            ctx = json.loads(rec["start"]["out"])["hookSpecificOutput"]["additionalContext"]
            self.assertIn(f"ACTIVE TASK: {rec['task']}", ctx)
            self.assertEqual(rec["finish"]["code"], 0, rec["finish"])
            self.assertIn("was recorded as", rec["stop"]["out"])  # Stop gate passed with a valid result
        self.assertIsNone(session.marker(self.project))
        self.assertTrue((self.project / ".alpa-studio/handoffs/LATEST.md").exists())

    def test_max_tasks_and_pause(self):
        for n in range(3):
            self.add(f"G{n}")
        self.assertEqual(self.run_loop(max_tasks=1)["stop_reason"], "max_tasks")
        session.pause(self.project, "mola")
        result = self.run_loop()
        self.assertEqual(result["stop_reason"], "paused")
        self.assertEqual(result["runs"], [])
        session.resume(self.project)
        self.assertEqual(len(self.run_loop()["runs"]), 2)

    def test_missing_result_retries_then_blocks_without_false_done(self):
        task_id = self.add("Half done", prompt="work [noresult]")
        result = self.run_loop()
        self.assertEqual([r["status"] for r in result["runs"]], ["interrupted", "blocked"])
        task = self.task(task_id)
        self.assertEqual(task["status"], "blocked")
        self.assertIn("not verified", task["last_error"])
        self.assertEqual(len(task["session_ids"]), 2)
        stop = json.loads(self.sessions()[0]["stop"]["out"])
        self.assertEqual(stop["decision"], "block")

    def test_usage_limit_stops_and_keeps_task_resumable(self):
        task_id = self.add("Limit", prompt="x [usage]")
        result = self.run_loop()
        self.assertEqual(result["stop_reason"], "usage_limit")
        self.assertEqual(result["exit_code"], session.EXIT_USAGE_LIMIT)
        task = self.task(task_id)
        self.assertEqual(task["status"], "interrupted")
        self.assertEqual(task["attempts"], 0)  # a limit does not burn an attempt
        self.assertIn(task_id, [t["id"] for t in session.classify(self.project)["eligible"]])

    def test_consecutive_crashes_stop_runner(self):
        self.add("Crash 1", prompt="a [crash]")
        self.add("Crash 2", prompt="b [crash]")
        result = self.run_loop()
        self.assertEqual(result["stop_reason"], "infra_failures")
        self.assertEqual(result["exit_code"], session.EXIT_FATAL)

    def test_approval_waits_while_independent_work_continues(self):
        apr = approval_create(self.project, "Yeni mekanik", "design-authority", "detay")["id"]
        gated = self.add("Approved work", requires_approval=apr)
        dependent = self.add("Dependent work", depends_on=[gated])
        free = self.add("Independent work")
        result = self.run_loop()
        self.assertEqual([r["task_id"] for r in result["runs"]], [free])
        self.assertEqual(result["stop_reason"], "waiting_for_owner")
        st = session.status(self.project)
        self.assertEqual(st["blocked_dependency"], [{"id": dependent, "waiting_on": [gated]}])
        self.assertEqual(st["waiting_approval"][0]["id"], gated)
        approval_decide(self.project, apr, "approved", "tamam")
        result = self.run_loop()
        self.assertEqual([r["task_id"] for r in result["runs"]], [gated, dependent])

    def test_conflict_goes_to_owner_approval(self):
        task_id = self.add("Conflicting", prompt="change [approval]")
        later = self.add("Next independent")
        result = self.run_loop()
        self.assertEqual([r["task_id"] for r in result["runs"]], [task_id, later])
        record = session.result_for(self.project, task_id)
        self.assertTrue(record["approval_id"])
        approvals = json.loads((self.project / ".alpa-studio/approvals.json").read_text())["items"]
        self.assertEqual({a["id"]: a["status"] for a in approvals}[record["approval_id"]], "pending")
        self.assertEqual(session.classify(self.project)["waiting_approval"][0]["id"], task_id)

    def test_auto_session_cannot_start_another_task(self):
        self.add("Single task", prompt="x [trystart]")
        self.run_loop()
        pretool = self.sessions()[0]["pretool"]
        self.assertEqual(pretool["code"], 2)
        self.assertIn("no other task can be started", pretool["err"])

    def test_dry_run_runs_nothing_and_rejects_bypass(self):
        self.add("Plan")
        result = self.run_loop(dry_run=True)
        self.assertEqual(len(result["plan"]), 1)
        self.assertIn("--permission-mode acceptEdits", result["plan"][0]["command"])
        # Headless workspaces cannot answer prompts; hooks provide the deterministic deny layer.
        self.assertIn("--allowedTools", result["plan"][0]["command"])
        self.assertIn("Bash(*)", result["plan"][0]["command"])
        self.assertIn("WebSearch", result["plan"][0]["command"])
        self.assertNotIn("dangerously", result["plan"][0]["command"])
        self.assertFalse(self.log.exists())
        with self.assertRaises(session.SessionError):
            session.build_command(self.project, {"id": "X"}, {"attempt": 1},
                                  {**session.execution_config(self.project), "permission_mode": "bypassPermissions"})

    def test_runner_creates_reviewable_task_branch(self):
        task_id = self.add("Branch task")
        result = self.run_loop(max_tasks=1)
        self.assertEqual(result["runs"][0]["status"], "done")
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=self.project, text=True,
                                capture_output=True, check=True).stdout.strip()
        self.assertEqual(branch, session.task_branch_name(task_id))

    def test_permission_denial_stops_immediately_and_keeps_task_retryable(self):
        first = self.add("Permission", prompt="x [permission]")
        second = self.add("Sonraki")
        result = self.run_loop()
        self.assertEqual(result["stop_reason"], "preflight_failed")
        self.assertEqual([r["task_id"] for r in result["runs"]], [first])
        self.assertEqual(self.task(first)["status"], "interrupted")
        self.assertEqual(self.task(first)["attempts"], 0)
        self.assertEqual(self.task(second)["status"], "queued")


class RecoveryTests(SessionFixture):
    def test_duplicate_runner_refused_and_stale_lock_recovered(self):
        self.add("Work")
        lock = self.project / ".alpa-studio/run/runner.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname()}))
        result = self.run_loop()
        self.assertEqual(result["stop_reason"], "locked")
        self.assertEqual(result["exit_code"], session.EXIT_LOCKED)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        lock.write_text(json.dumps({"pid": dead.pid, "host": socket.gethostname()}))
        self.assertEqual(self.run_loop()["stop_reason"], "no_eligible")
        self.assertFalse(lock.exists())

    def test_orphaned_running_task_is_recovered_and_finished(self):
        task_id = self.add("Interrupted")
        session.start_task(self.project, task_id, mode="auto")  # runner died mid-task
        result = self.run_loop()
        state = json.loads((self.project / ".alpa-studio/run/run-state.json").read_text())
        self.assertEqual(state["runner"]["recovered"], [task_id])
        self.assertEqual(result["runs"][0]["task_id"], task_id)
        self.assertEqual(self.task(task_id)["status"], "done")

    def test_cas_conflict_detected(self):
        path = self.project / ".alpa-studio/tasks.json"
        rev = json.loads(path.read_text()).get("revision", 0)
        session.update_json(path, lambda d: None, {"items": []}, expected_revision=rev)
        with self.assertRaises(session.SessionError):
            session.update_json(path, lambda d: None, {"items": []}, expected_revision=rev)

    def test_blocked_task_can_be_requeued_without_deleting_history(self):
        task_id = self.add("Tekrar")
        session.finish_task(self.project, task_id, "blocked", "no permission", ["log"],
                            ["cmd=test;result=unverified"])
        result_path = self.project / f".alpa-studio/results/{task_id}.json"
        self.assertTrue(result_path.exists())
        retried = session.retry_task(self.project, task_id, "permission policy fixed")
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(retried["attempts"], 0)
        self.assertTrue(result_path.exists())

    def test_auto_git_hook_limits_writes_to_matching_task_branch(self):
        task_id = self.add("Git")
        branch = session.task_branch_name(task_id)
        subprocess.run(["git", "switch", "-c", branch], cwd=self.project, check=True,
                       stdout=subprocess.DEVNULL)
        env = {"ALPA_RUN_MODE": "auto", "ALPA_TASK_ID": task_id}
        broad = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                           "tool_input": {"command": "git add ."}}, **env)
        self.assertEqual(broad.returncode, 2)
        broad_update = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                  "tool_input": {"command": "git add -u"}}, **env)
        self.assertEqual(broad_update.returncode, 2)
        wrong_push = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                "tool_input": {"command": "git push origin main"}}, **env)
        self.assertEqual(wrong_push.returncode, 2)
        right_push = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                "tool_input": {"command": f"git push origin {branch}"}}, **env)
        self.assertEqual(right_push.returncode, 0, right_push.stderr)
        wrong_message = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                   "tool_input": {"command": "git commit -m 'update'"}}, **env)
        self.assertEqual(wrong_message.returncode, 2)
        broad_commit = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                  "tool_input": {"command": f"git commit -am '{task_id}: update'"}}, **env)
        self.assertEqual(broad_commit.returncode, 2)
        right_message = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                   "tool_input": {"command": f"git commit -m '{task_id}: update'"}}, **env)
        self.assertEqual(right_message.returncode, 0, right_message.stderr)


class GateTests(SessionFixture):
    def test_done_requires_evidence_gates_and_passing_tests(self):
        task_id = self.add("Gated", required_gates=["unity-editmode"])
        with self.assertRaises(session.SessionError):
            session.finish_task(self.project, task_id, "done", "summary")
        with self.assertRaises(session.SessionError):
            session.finish_task(self.project, task_id, "done", "summary", ["evidence"], ["cmd=unit;result=failed"])
        with self.assertRaises(session.SessionError):  # Unity unavailable -> unverified is not a pass
            session.finish_task(self.project, task_id, "done", "summary", ["evidence"],
                                ["cmd=unity-editmode;result=unverified"])
        record = session.finish_task(self.project, task_id, "blocked", "no Unity", ["log"],
                                     ["cmd=unity-editmode;result=unverified"])
        self.assertEqual(record["unverified"], ["unity-editmode"])
        self.assertEqual(self.task(task_id)["status"], "blocked")

    def test_secrets_are_redacted(self):
        task_id = self.add("Gizli")
        record = session.finish_task(self.project, task_id, "blocked", "token=abcdef123456 sk-" + "a" * 24, ["evidence"])
        handoff = (self.project / ".alpa-studio/handoffs/LATEST.md").read_text()
        for text in (record["summary"], handoff):
            self.assertNotIn("abcdef123456", text)
            self.assertNotIn("a" * 24, text)

    def test_stop_gate_t069_stale_result_in_same_commit_is_not_completion(self):
        """T-069: handoff + ledger committed together made an old result look like completion."""
        task_id = self.add("T-069 regresyon")
        session.start_task(self.project, task_id, mode="manual")
        session.finish_task(self.project, task_id, "done", "old attempt", ["old"])
        stale = session.result_for(self.project, task_id)
        session.update_task(self.project, task_id, {"status": "queued"})
        marker = session.start_task(self.project, task_id, mode="manual")  # new attempt, new nonce
        stale["recorded_ts"] = 0
        (self.project / ".alpa-studio/results" / f"{task_id}.json").write_text(json.dumps(stale))
        subprocess.run(["git", "add", "-A"], cwd=self.project, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "handoff+ledger"],
                       cwd=self.project, check=True)
        self.assertNotEqual(stale["nonce"], marker["nonce"])
        first = self.hook({"hook_event_name": "Stop", "session_id": "S1", "stop_hook_active": False})
        self.assertEqual(json.loads(first.stdout)["decision"], "block")
        second = self.hook({"hook_event_name": "Stop", "session_id": "S1", "stop_hook_active": True})
        self.assertEqual(second.stdout.strip(), "")  # never loops
        session.finish_task(self.project, task_id, "done", "new attempt", ["test output"])
        done = self.hook({"hook_event_name": "Stop", "session_id": "S1", "stop_hook_active": False})
        self.assertIn("was recorded as", json.loads(done.stdout)["systemMessage"])
        self.assertIsNone(session.marker(self.project))  # manual: the next continue phrase gets a fresh task

    def test_stop_gate_blocks_at_most_twice(self):
        task_id = self.add("No endless loop")
        session.start_task(self.project, task_id, mode="manual")
        decisions = []
        for _ in range(3):
            out = self.hook({"hook_event_name": "Stop", "session_id": "S2", "stop_hook_active": False}).stdout
            decisions.append(json.loads(out).get("decision"))
        self.assertEqual(decisions, ["block", "block", None])

    def test_stop_gate_ignores_other_sessions(self):
        task_id = self.add("Someone else's task")
        session.start_task(self.project, task_id, mode="manual")
        session.claim_session(self.project, "OWNER")
        out = self.hook({"hook_event_name": "Stop", "session_id": "OTHER", "stop_hook_active": False})
        self.assertEqual(out.stdout.strip(), "")


class ContextTests(SessionFixture):
    def test_session_start_context_is_bounded_and_keeps_contract(self):
        for n in range(30):
            self.add(f"Long title {n} " + "x" * 300)
        handoff = self.project / ".alpa-studio/handoffs/LATEST.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("\n".join(f"line {n} " + "y" * 400 for n in range(500)))
        session.start_task(self.project, mode="manual")
        ctx = session.session_context(self.project, "clear")
        self.assertLessEqual(len(ctx), session.execution_config(self.project)["context_budget_chars"])
        self.assertIn("ACTIVE TASK", ctx)
        self.assertIn("scripts/alpa task finish", ctx)

    def test_precompact_snapshot_is_read_back_after_compact(self):
        task_id = self.add("Compaction")
        session.start_task(self.project, task_id, mode="manual")
        session.progress(self.project, task_id, "implementation", "half done", "write tests")
        (self.project / "Assets").mkdir(exist_ok=True)
        (self.project / "Assets/new.cs").write_text("// new")
        out = self.hook({"hook_event_name": "PreCompact", "session_id": "S", "trigger": "auto"})
        self.assertEqual(out.returncode, 0)
        snap = json.loads((self.project / ".alpa-studio/checkpoints/precompact-latest.json").read_text())
        self.assertEqual(snap["task"]["task_id"], task_id)
        self.assertEqual(snap["progress"]["phase"], "implementation")
        start = self.hook({"hook_event_name": "SessionStart", "session_id": "S", "source": "compact"})
        ctx = json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("State before compaction", ctx)
        self.assertIn("phase=implementation", ctx)

    def test_locked_decisions_survive_rotation(self):
        apr = approval_create(self.project, "Art Bible v1", "design-authority", "locked")["id"]
        approval_decide(self.project, apr, "approved", "ok")
        ctx = session.session_context(self.project, "startup")
        self.assertIn("Art Bible v1", ctx)
        self.assertIn("waiting_for_approval", ctx)

    def test_manual_continue_without_task_id(self):
        first = self.add("First")
        self.add("Second")
        result = subprocess.run([str(self.project / "scripts/alpa"), "task", "start"], text=True,
                                capture_output=True, cwd=self.project, env={**os.environ})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(session.marker(self.project)["task_id"], first)


class BacklogSourceTests(SessionFixture):
    def test_backlog_parsing_and_state(self):
        cfg_path = self.project / ".alpa-studio/config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["execution"]["task_source"] = "backlog"
        cfg_path.write_text(json.dumps(cfg))
        backlog = self.project / "docs/BACKLOG.md"
        backlog.parent.mkdir(exist_ok=True)
        backlog.write_text("# Backlog\n- [x] M-1 done\n- [ ] M-2 open work\n- [ ] M-3 BLOCKED: no device\n"
                           "- [ ] M-4 store account (human)\n- [ ] **M-5** next\n")
        buckets = session.classify(self.project)
        self.assertEqual([t["id"] for t in buckets["eligible"]], ["M-2", "M-5"])
        self.assertEqual([t["id"] for t in buckets["done"]], ["M-1"])
        self.assertEqual([t["id"] for t in buckets["blocked"]], ["M-3"])
        self.assertEqual([t["id"] for t in buckets["needs_owner"]], ["M-4"])
        self.assertEqual(buckets["eligible"][0]["prompt"], "/next-task M-2")
        result = self.run_loop()
        self.assertEqual([r["task_id"] for r in result["runs"]], ["M-2", "M-5"])
        self.assertEqual(result["stop_reason"], "waiting_for_owner")
        self.assertIn("[ ] M-2", backlog.read_text())  # runner never rewrites the owner's backlog
        self.assertEqual(session.tasks(self.project)[1]["status"], "done")


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class UpgradeTests(SessionFixture):
    def make_legacy(self):
        cfg_path = self.project / ".alpa-studio/config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg.pop("execution")
        cfg["framework_version"] = "0.2.2"
        cfg_path.write_text(json.dumps(cfg))
        self.add("Old task")
        apr = approval_create(self.project, "Bekleyen", "design-authority", "")["id"]
        return apr

    def test_claude_detection_uses_argv_not_command_name(self):
        # Claude Code's binary is version-named (lsof shows '2.1.322'), so `lsof -c claude` misses it.
        from alpa_studio import upgrade as upgrade_mod
        ps = ("  101 claude\n  102 /home/x/.local/share/claude/versions/2.1.322 -p hi\n"
              "  103 node /opt/lib/node_modules/@anthropic-ai/claude-code/cli.js\n  104 /bin/zsh\n  105 claudette\n")
        with mock.patch.object(upgrade_mod.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, stdout=ps)):
            self.assertEqual(upgrade_mod._claude_pids(), [101, 102, 103])

    def test_cli_upgrade_dry_run(self):
        self.make_legacy()
        out = subprocess.run([sys.executable, "-m", "alpa_studio.cli", "upgrade", "--project", str(self.project),
                              "--task-source", "backlog"], text=True, capture_output=True,
                             env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        self.assertEqual(out.returncode, 0, out.stderr)
        report = json.loads(out.stdout)
        self.assertFalse(report["applied"])
        self.assertIn("execution.task_source = backlog", report["schema_changes"])

    def test_dry_run_is_read_only(self):
        self.make_legacy()
        before = _tree_digest(self.project)
        with mock.patch("alpa_studio.upgrade.active_session_blockers", return_value=[]):
            report = upgrade(self.project, task_source="backlog")
        self.assertEqual(report["status"], "MIGRATION_READY")
        self.assertFalse(report["applied"])
        self.assertTrue(report["schema_changes"])
        self.assertEqual(before, _tree_digest(self.project))

    def test_apply_preserves_history_and_is_idempotent(self):
        apr = self.make_legacy()
        tasks_before = json.loads((self.project / ".alpa-studio/tasks.json").read_text())["items"]
        with mock.patch("alpa_studio.upgrade.active_session_blockers", return_value=[]):
            report = upgrade(self.project, apply=True)
        self.assertEqual(report["status"], "MIGRATED", report)
        cfg = json.loads((self.project / ".alpa-studio/config.json").read_text())
        self.assertEqual(cfg["execution"]["policy"], "auto")
        tasks_after = json.loads((self.project / ".alpa-studio/tasks.json").read_text())["items"]
        self.assertEqual([t["id"] for t in tasks_before], [t["id"] for t in tasks_after])
        approvals = json.loads((self.project / ".alpa-studio/approvals.json").read_text())["items"]
        self.assertEqual(approvals[0]["id"], apr)
        self.assertTrue((self.project / report["backup"] / "manifest.json").exists())
        with mock.patch("alpa_studio.upgrade.active_session_blockers", return_value=[]):
            self.assertEqual(upgrade(self.project, apply=True)["status"], "UP_TO_DATE")
            restored = upgrade(self.project, rollback=report["backup"])
        self.assertTrue(restored["ok"])
        cfg = json.loads((self.project / ".alpa-studio/config.json").read_text())
        self.assertNotIn("execution", cfg)

    def test_apply_refused_while_session_active(self):
        self.make_legacy()
        events = self.project / ".alpa-studio/events.json"
        events.write_text(json.dumps({"schema": 1, "items": [{"at": session.now_iso(), "event": "PreToolUse"}]}))
        before = _tree_digest(self.project)
        report = upgrade(self.project, apply=True)
        self.assertEqual(report["status"], "BLOCKED_ACTIVE_SESSION")
        self.assertEqual(before, _tree_digest(self.project))

    def test_recent_stop_without_live_process_is_not_a_blocker(self):
        from alpa_studio import upgrade as upgrade_mod
        events = self.project / ".alpa-studio/events.json"
        events.write_text(json.dumps({"schema": 1, "items": [{"at": session.now_iso(), "event": "Stop"}]}))
        with mock.patch.object(upgrade_mod, "claude_processes_in", return_value=[]), \
             mock.patch("alpa_studio.session.lock_info", return_value=None):
            self.assertEqual(upgrade_mod.active_session_blockers(self.project), [])

    def test_history_change_triggers_rollback(self):
        self.make_legacy()
        import alpa_studio.project as project_mod
        real_install = project_mod.install

        def corrupting_install(*args, **kwargs):
            out = real_install(*args, **kwargs)
            path = self.project / ".alpa-studio/tasks.json"
            data = json.loads(path.read_text())
            data["items"][0]["status"] = "done"
            path.write_text(json.dumps(data))
            return out
        with mock.patch.object(project_mod, "install", corrupting_install), \
             mock.patch("alpa_studio.upgrade.active_session_blockers", return_value=[]):
            report = upgrade(self.project, apply=True)
        self.assertEqual(report["status"], "ROLLED_BACK")
        data = json.loads((self.project / ".alpa-studio/tasks.json").read_text())
        self.assertEqual(data["items"][0]["status"], "queued")


@unittest.skipUnless(os.environ.get("ALPA_REAL_CLAUDE") == "1", "opt-in: ALPA_REAL_CLAUDE=1 runs real Claude Code")
class RealClaudeIntegrationTest(SessionFixture):
    """Three sequential tasks, three distinct real Claude sessions, zero manual intervention."""

    def test_real_three_tasks(self):
        os.environ.pop("ALPA_CLAUDE_BIN", None)
        if not shutil.which("claude"):
            self.skipTest("claude CLI not found")
        cfg_path = self.project / ".alpa-studio/config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["execution"].update(model=os.environ.get("ALPA_REAL_MODEL", "haiku"), max_turns=12, timeout_seconds=600)
        cfg_path.write_text(json.dumps(cfg))
        ids = []
        for n in (1, 2, 3):
            ids.append(self.add(f"File {n}", prompt=(
                f"Create notes/task{n}.txt in the project root and write only 'task {n}' into it. "
                "Use the file path as evidence; as the test use 'cmd=cat notes/task{n}.txt;result=passed'.")))
        result = self.run_loop(max_tasks=5)
        report = Path(os.environ.get("ALPA_REAL_REPORT", str(Path(self.temp.name) / "real.json")))
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        self.assertEqual(result["stop_reason"], "no_eligible", result)
        sids = [r["session_id"] for r in result["runs"]]
        self.assertEqual(len(sids), 3)
        self.assertEqual(len(set(sids)), 3, sids)
        for n, task_id in enumerate(ids, 1):
            self.assertEqual(self.task(task_id)["status"], "done", result)
            self.assertEqual((self.project / f"notes/task{n}.txt").read_text().strip(), f"task {n}")


if __name__ == "__main__":
    unittest.main()
