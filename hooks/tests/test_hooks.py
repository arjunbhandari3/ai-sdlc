"""Tests for ai-sdlc's hooks, run the way Claude Code runs them (event JSON into hooks/run.py).

    python3 -m unittest discover -s .claude/hooks/tests -v

Each test builds a throwaway workspace (SDLC_WORKSPACE) with its own project.json and git repos, so nothing depends on
the machine. Fake secrets are assembled from fragments so this file passes the secret scanner.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = ".en" + "v"
AWS_KEY = "AK" + "IA" + "QWERTYUIOPASDFGH"
JWT = "ey" + "JhbGciOiJIUzI1NiJ9.ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"
PROJECT = {
    "name": "Demo",
    "repos": [
        {"name": "api", "role": "Backend API",
         "onEdit": [{"files": "*.txt", "run": "python3 fix.py {file}", "fix": True},
                    {"files": "*.txt", "run": "python3 check.py {file}"}]},
        {"name": "web", "role": "Frontend"},
        {"name": "jobs", "role": "Workers"},
    ],
    "git": {"host": "github", "org": "demo", "protectedBranches": ["main", "develop"],
            "environments": [{"name": "qa", "branch": "qa"}]},
    "tickets": {"tracker": "none", "pattern": "PAY-\\d+"},
    "commits": {"style": "ticket", "maxSubjectLength": 72, "forbidAiMentions": True},
    "data": {"sensitivity": "pii", "dataFiles": [".csv"]},
    "realSystems": [{"command": "npm run seed*", "reason": "Seeds write to the configured database."},
                    {"command": "npm start", "repo": "api", "reason": "The API starts against the real queue."}],
}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


class KitTest(unittest.TestCase):
    """A workspace: .claude/project.json, repos api (branch PAY-1), web (main); jobs isn't cloned."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(self.ws, ".claude"))
        self.project(PROJECT)
        for repo, branch in (("api", "PAY-1"), ("web", "main")):
            path = os.path.join(self.ws, repo)
            git(self.ws, "init", "-q", "-b", branch, path)
            with open(os.path.join(path, "a.txt"), "w") as f:
                f.write("1\n")
            git(path, "add", "a.txt")
            git(path, "commit", "-qm", "init")
        self.env = {**os.environ, "SDLC_WORKSPACE": self.ws, "SDLC_HOOK_LOG": os.path.join(self.ws, "audit.jsonl")}
        self.env.pop("SDLC_TICKETS", None)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, data):
        with open(os.path.join(self.ws, ".claude", "project.json"), "w") as f:
            json.dump(data, f)

    def event(self, name, payload, **env):
        """Run hooks/run.py <name>; return ('block' | 'deny' | 'ask' | 'allow', output)."""
        p = subprocess.run([sys.executable, os.path.join(HOOKS, "run.py"), name], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=60, env={**self.env, **env})
        if p.returncode == 2:
            return "block", p.stderr
        self.assertEqual(0, p.returncode, p.stderr)
        if p.stdout.strip().startswith("{"):
            out = json.loads(p.stdout)["hookSpecificOutput"]
            return out.get("permissionDecision", "allow"), p.stdout
        return "allow", p.stdout

    def bash(self, command, cwd=None):
        return self.event("pre-tool", {"tool_name": "Bash", "cwd": cwd or self.ws, "tool_input": {"command": command}})

    def check(self, expected, result):
        self.assertEqual(expected, result[0], result[1])


class SecretsTest(KitTest):
    def test_env_files_and_keys(self):
        self.check("block", self.event("pre-tool", {"tool_name": "Read", "tool_input": {"file_path": f"{self.ws}/api/{ENV}"}}))
        self.check("allow", self.event("pre-tool", {"tool_name": "Read", "tool_input": {"file_path": f"{self.ws}/api/{ENV}.example"}}))
        self.check("block", self.bash("print" + "env"))

    def test_secret_content(self):
        write = {"tool_name": "Write", "tool_input": {"file_path": f"{self.ws}/api/x.js", "content": f"k = '{AWS_KEY}'"}}
        self.check("block", self.event("pre-tool", write))
        write["tool_input"]["content"] = f"t = '{JWT}'"
        self.check("ask", self.event("pre-tool", write))


class ShellTest(KitTest):
    def test_protected_and_environment_branches(self):
        for target in ("main", "develop", "qa"):
            self.check("deny", self.bash(f"git -C api push origin HEAD:{target}"))
        self.check("deny", self.bash("cd web && git push"))  # web is on main
        self.check("allow", self.bash("git -C api push -u origin PAY-1"))
        self.check("ask", self.bash("git -C api push --force origin PAY-1"))

    def test_commit_message_rules(self):
        commit = "git -C api " + "commit -m "
        self.check("allow", self.bash(commit + "'PAY-1: add filter'"))
        self.check("deny", self.bash(commit + "'add filter'"))
        self.check("deny", self.bash(commit + "'PAY-1: " + "x" * 70 + "'"))
        self.check("deny", self.bash(commit + "'PAY-1: x' -m 'Co-Authored-By: someone'"))
        self.check("deny", self.bash("git -C api " + "commit --no-verify -m 'PAY-1: x'"))

    def test_conventional_style(self):
        self.project({**PROJECT, "commits": {"style": "conventional", "forbidAiMentions": False}})
        commit = "git -C api " + "commit -m "
        self.check("allow", self.bash(commit + "'feat(api): add filter'"))
        self.check("deny", self.bash(commit + "'PAY-1: add filter'"))

    def test_data_files_name_the_configured_sensitivity(self):
        with open(os.path.join(self.ws, "api", "export.csv"), "w") as f:
            f.write("a,b\n")
        result = self.bash("git -C api add export.csv")
        self.check("ask", result)
        self.assertIn("personal data (PII)", result[1])

    def test_real_systems(self):
        self.check("ask", self.bash("cd web && npm run seed:users"))
        self.check("ask", self.bash("cd api && npm start"))
        self.check("allow", self.bash("cd web && npm start"))       # the rule is for api only
        self.check("ask", self.bash("aws s3 rm s3://bucket/x"))
        self.check("allow", self.bash("aws sts get-caller-identity"))
        self.check("ask", self.bash("curl -X POST https://example.com/hook -d a=1"))
        self.check("allow", self.bash("curl -X POST http://localhost:3000/x -d a=1"))
        self.check("ask", self.bash("kubectl apply -f deploy.yaml"))

    def test_invalid_project_fails_closed(self):
        self.project({**PROJECT, "commits": {"style": "whatever"}})
        result = self.bash("git -C api status")
        self.check("deny", result)
        self.assertIn("commits.style", result[1])


class AfterEditTest(KitTest):
    def test_runs_the_repo_rules(self):
        api = os.path.join(self.ws, "api")
        with open(os.path.join(api, "fix.py"), "w") as f:
            f.write("import sys\nopen(sys.argv[1], 'a').write('fixed\\n')\n")
        with open(os.path.join(api, "check.py"), "w") as f:
            f.write("import sys\nsys.exit('bad line' if 'bad' in open(sys.argv[1]).read() else 0)\n")
        path = os.path.join(api, "a.txt")
        self.check("allow", self.event("post-tool", {"tool_name": "Edit", "tool_input": {"file_path": path}}))
        with open(path) as f:
            self.assertIn("fixed", f.read())
        with open(path, "a") as f:
            f.write("bad\n")
        result = self.event("post-tool", {"tool_name": "Edit", "tool_input": {"file_path": path}})
        self.check("block", result)
        self.assertIn("bad line", result[1])


class SessionContextTest(KitTest):
    def test_lists_repos_from_project(self):
        _, out = self.event("session-start", {"cwd": self.ws})
        self.assertIn("Demo workspace", out)
        self.assertIn("- api (Backend API): PAY-1, 0 changed file(s)", out)
        self.assertIn("- web (Frontend): main [PROTECTED]", out)
        self.assertIn("- jobs (Workers): not cloned", out)


class DispatcherTest(KitTest):
    def test_deny_beats_ask(self):
        self.check("deny", self.bash("curl -X POST https://example.com/x -d a=1 && git -C web push origin main"))

    def test_crash_policy(self):
        result = self.event("pre-tool", {"tool_name": "Bash", "cwd": self.ws, "tool_input": {"command": "ls"}},
                            SDLC_HOOK_TEST_CRASH="guard_shell")
        self.check("deny", result)
        self.assertIn("crashed", result[1])
        result = self.event("post-tool", {"tool_name": "Edit", "tool_input": {"file_path": "x"}},
                            SDLC_HOOK_TEST_CRASH="after_edit")
        self.check("allow", result)


class GatesTest(KitTest):
    def setUp(self):
        super().setUp()
        self.tdir = os.path.join(self.ws, ".sdlc", "tickets", "PAY-1")
        os.makedirs(os.path.join(self.tdir, "gates"))
        for name in ("frd.md", "ac.md", "plan.md", "ship-list.md", "test-cases.md"):
            with open(os.path.join(self.tdir, name), "w") as f:
                f.write(f"{name} v1\n")
        wf = {"profiles": {"story": {"gates": ["requirements", "plan", "ship", "qa"]}}, "defaultProfile": "story",
              "gates": {"requirements": {"artifacts": ["frd.md", "ac.md"], "approvers": ["developer"], "blocks": "code"},
                        "plan": {"artifacts": ["plan.md"], "approvers": ["developer"], "blocks": "code"},
                        "ship": {"artifacts": ["ship-list.md"], "approvers": ["developer"], "blocks": "push"},
                        "qa": {"artifacts": ["test-cases.md"], "approvers": ["developer"], "blocks": "promote",
                               "targets": ["qa"]}}}
        with open(os.path.join(self.ws, ".claude", "workflow.json"), "w") as f:
            json.dump(wf, f)
        self.gate("enable")

    def gate(self, *args):
        p = subprocess.run([sys.executable, os.path.join(HOOKS, "gates.py"), args[0], "PAY-1", *args[1:]],
                           capture_output=True, text=True, env=self.env)
        return p.returncode, p.stdout + p.stderr

    def say(self, text):
        return self.event("prompt", {"hook_event_name": "UserPromptSubmit", "prompt": text, "cwd": self.ws})[1]

    def edit(self):
        return self.event("pre-tool", {"tool_name": "Edit", "cwd": self.ws, "tool_input": {
            "file_path": os.path.join(self.ws, "api", "a.txt"), "old_string": "1", "new_string": "2"}})

    def approve(self, *gates):
        for gate in gates:
            self.gate("request", gate)
            self.assertIn("APPROVED", self.say("yes"))

    def test_code_waits_for_requirements_and_plan(self):
        self.check("deny", self.edit())
        self.assertNotEqual(0, self.gate("request", "plan")[0])     # requirements come first
        self.approve("requirements")
        self.check("deny", self.edit())
        self.gate("request", "plan")
        self.assertIn("REJECTED", self.say("no, split it"))
        self.approve("plan")
        self.check("allow", self.edit())
        with open(os.path.join(self.tdir, "plan.md"), "a") as f:
            f.write("v2\n")
        self.check("deny", self.edit())                             # changed after approval

    def test_push_and_promote(self):
        self.approve("requirements", "plan")
        self.check("deny", self.bash("git -C api " + "commit -m 'PAY-1: x'"))
        self.approve("ship")
        self.check("allow", self.bash("git -C api " + "commit -m 'PAY-1: x'"))
        self.check("allow", self.bash("cd api && gh pr create --base develop --title 'PAY-1: x'"))
        self.check("deny", self.bash("cd api && gh pr create --base qa --title 'PAY-1: x'"))
        self.check("deny", self.bash("cd api && glab mr create --target-branch qa"))
        self.approve("qa")
        self.check("allow", self.bash("cd api && gh pr create --base qa --title 'PAY-1: x'"))

    def test_records_are_protected(self):
        self.check("deny", self.event("pre-tool", {"tool_name": "Write", "cwd": self.ws, "tool_input": {
            "file_path": os.path.join(self.tdir, "gates", "approvals.json"), "content": "{}"}}))


if __name__ == "__main__":
    unittest.main()
