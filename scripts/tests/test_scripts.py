"""Tests for the Python scripts (standard library only, no network). Run from anywhere:

    python3 -m unittest discover -s .claude/scripts/tests -v

Tickets live in a temporary folder (SDLC_TICKETS); git cases use throwaway repos with local bare remotes.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.TemporaryDirectory()
TICKETS = os.path.join(os.path.realpath(TMP.name), "tickets")
os.environ["SDLC_TICKETS"] = TICKETS  # before the imports: the scripts read it once

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.dirname(SCRIPTS)
# The kit's defaults, not a team's project.json: a workspace whose .claude has only the kit's workflow.json
WORKSPACE = os.path.join(os.path.realpath(TMP.name), "ws")
os.makedirs(os.path.join(WORKSPACE, ".claude"))
with open(os.path.join(KIT, "workflow.json")) as src, open(os.path.join(WORKSPACE, ".claude", "workflow.json"), "w") as dst:
    dst.write(src.read())
os.environ["SDLC_WORKSPACE"] = WORKSPACE

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
import bitbucket  # noqa: E402
import jira  # noqa: E402
import sdlc  # noqa: E402
import reference_tables  # noqa: E402
import tickets  # noqa: E402


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def output(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return buf.getvalue()


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True).stdout


def run(script, *args, env=None, cwd=None):
    merged = {k: v for k, v in {**os.environ, **(env or {})}.items() if v is not None}  # None drops a variable
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args], capture_output=True, text=True,
                       env=merged, cwd=cwd)
    return p.returncode, p.stdout + p.stderr


class TicketsTest(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.join(TICKETS, "PAY-1")
        write(os.path.join(self.folder, "ticket.json"), json.dumps({
            "summary": "Fake | ticket", "stage": "verify", "tracker": {"status": "In Progress"},
            "repo_state": {"api": {"pr": {"develop": "https://github.com/acme/api/pull/7 (draft)"}}},
            "history": [{"at": "2026-01-01T10:00:00Z", "stage": "build", "note": "done"}]}))
        write(os.path.join(self.folder, "test-results.json"), json.dumps({
            "now": {"results": [{"scenario": "s", "case": "a", "ac": ["AC-1", "AC-2"], "ok": True},
                                {"scenario": "s", "case": "b", "ac": ["AC-2"], "ok": False}]},
            "before": {"results": [{"scenario": "s", "case": "a", "ac": ["AC-1"], "ok": False}]}}))

    def tearDown(self):
        shutil.rmtree(TICKETS, ignore_errors=True)

    def test_status(self):
        md = tickets.status_md("PAY-1")
        self.assertIn("Stage: **verify** · Ticket: In Progress", md)
        self.assertIn("| AC-2 | 1/2 | 0/1 |", md)
        self.assertIn("[#7](https://github.com/acme/api/pull/7) (draft)", md)

    def test_overview_lists_ticket_folders(self):
        os.makedirs(os.path.join(TICKETS, "not-a-ticket"))
        md = tickets.overview_md()
        self.assertIn("| [PAY-1](#pay-1) | Fake / ticket | verify | – | 1/2 | 1 |", md)
        self.assertNotIn("not-a-ticket", md)

    def test_clean_lists_then_removes(self):
        with mock.patch.object(sys, "argv", ["tickets.py", "clean", "PAY-1"]):
            self.assertIn("Would remove", output(tickets.clean, "PAY-1"))
        self.assertTrue(os.path.isdir(self.folder))
        with mock.patch.object(sys, "argv", ["tickets.py", "clean", "PAY-1", "--yes"]):
            output(tickets.clean, "PAY-1")
        self.assertFalse(os.path.exists(self.folder))


class JiraTest(unittest.TestCase):
    def test_utc_and_adf(self):
        self.assertEqual("2026-10-06T04:15:00+00:00", jira.utc("2026-10-06T10:00:00.000+0545"))
        doc = jira.to_adf("## Status\nAll good\n\n- one\n- two\n\n| a | b |\n|---|---|")
        self.assertEqual(["heading", "paragraph", "bulletList", "codeBlock"], [n["type"] for n in doc["content"]])


class BitbucketTest(unittest.TestCase):
    def setUp(self):
        self.pr = os.path.join(TICKETS, "PAY-2", "pr")
        self.shot = write(os.path.join(TICKETS, "PAY-2", "evidence", "a.png"), "fake png")

    def tearDown(self):
        shutil.rmtree(TICKETS, ignore_errors=True)

    def test_keep_sent_replaces_drafts(self):
        for name in ("dev.md", "dev-assets.md", "dev.html", "qa.md"):
            write(os.path.join(self.pr, name), name)
        bitbucket.keep_sent(os.path.join(self.pr, "dev-assets.md"), 41, "sent")
        self.assertEqual(["41.md", "qa.md"], sorted(os.listdir(self.pr)))

    def test_assets_one_commit_for_all_drafts(self):
        repo = os.path.join(TICKETS, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        for key, value in (("user.name", "t"), ("user.email", "t@t")):  # CI runners have no git identity
            git(repo, "config", key, value)
        git(repo, "remote", "add", "origin", "git@bitbucket.org:acme/api.git")
        dev = write(os.path.join(self.pr, "dev.md"), f"(drag in {self.shot})\n")
        qa = write(os.path.join(self.pr, "qa.md"), f"(drag in {self.shot})\n")
        out = output(bitbucket.assets, repo, dev, qa)
        self.assertIn("branch\tPAY-2-assets\nimages\t1", out)
        commit = out.split("\t")[1].split("\n")[0]
        with open(os.path.join(self.pr, "qa-assets.md")) as f:
            self.assertEqual(f"![a.png](https://bitbucket.org/acme/api/raw/{commit}/01-a.png)\n", f.read())


class CheckTargetsTest(unittest.TestCase):
    """A feature branch importing a constant one target removed, and two targets with the same conflict."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self.tmp.name)
        origin, self.repo = os.path.join(root, "origin.git"), os.path.join(root, "web")
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
        subprocess.run(["git", "clone", "-q", origin, self.repo], check=True, capture_output=True)
        git(self.repo, "checkout", "-q", "-b", "main")
        self.commit({"src/static/constants.js": "export const SINGLE = 1;\n", "src/a.js": "const a = 1;\n"})
        git(self.repo, "checkout", "-q", "-b", "develop")
        self.commit({"src/static/constants.js": "export const OTHER = 2;\n"})
        for target in ("qa", "staging"):
            git(self.repo, "checkout", "-q", "-b", target, "main")
            self.commit({"src/a.js": "const a = 2;\n"})
        git(self.repo, "checkout", "-q", "-b", "PAY-1", "main")
        self.commit({"src/a.js": 'import { SINGLE } from "static/constants";\nconst a = SINGLE;\n'})
        git(self.repo, "push", "-q", "origin", "main", "develop", "qa", "staging")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, files):
        for path, text in files.items():
            write(os.path.join(self.repo, path), text)
        git(self.repo, "add", *files)
        git(self.repo, "commit", "-qm", "change")

    def test_table(self):
        code, out = run("check_targets.py", self.repo, "PAY-1", "develop", "qa", "staging", "nope")
        self.assertEqual(0, code, out)
        rows = {line.split(" | ")[0].strip("| "): line for line in out.splitlines() if line.startswith("| ")}
        self.assertIn("**missing exports:** a.js: `SINGLE`", rows["develop"])
        self.assertIn("resolve by hand", rows["qa"])
        self.assertIn("same target versions as qa", rows["staging"])
        self.assertIn("no such branch", rows["nope"])


class KitCliTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TICKETS, ignore_errors=True)

    def test_help_unknown_and_refused(self):
        self.assertEqual(0, run("sdlc.py", "help")[0])
        self.assertEqual(2, run("sdlc.py", "nope")[0])
        code, out = run("sdlc.py", "jira", "comment", "PAY-1", "x.md")
        self.assertNotEqual(0, code)
        self.assertIn("use one of check, comments, fetch", out)

    def test_status_and_validate(self):
        write(os.path.join(TICKETS, "PAY-3", "ticket.json"), json.dumps({"summary": "Fake", "stage": "plan"}))
        self.assertIn("| [PAY-3](#pay-3) | Fake | plan |", run("sdlc.py", "status")[1])
        code, out = run("sdlc.py", "validate")
        self.assertEqual(0, code, out)
        self.assertIn("workflow.json: valid", out)

    def test_changelog_since(self):
        text = "# Changelog\n\n## 1.2.0 (x)\n\n- b\n\n## 1.1.0 (x)\n\n- a\n\n## 1.0.0 (x)\n"
        self.assertEqual("## 1.2.0 (x)\n\n- b\n## 1.1.0 (x)\n\n- a", sdlc.changelog_since(text, "1.0.0"))


class InitTest(unittest.TestCase):
    """sdlc init drafts project.json from the repos in a workspace."""

    def test_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.realpath(tmp)
            remote = os.path.join(ws, "remotes", "api.git")
            api = os.path.join(ws, "api")
            git(ws, "init", "-q", "--bare", remote)
            git(ws, "init", "-q", "-b", "main", api)
            write(os.path.join(api, "package.json"), json.dumps({
                "description": "Payments API", "devDependencies": {"prettier": "3", "eslint": "9"},
                "scripts": {"seed:users": "node seed.js", "test": "mocha"}}))
            git(api, "add", ".")
            for subject in ("feat(api): add retry", "fix: handle decline", "chore: bump deps"):
                git(api, "commit", "-q", "--allow-empty", "-m", subject)
            for branch in ("develop", "qa", "PAY-7", "PAY-8-retry"):
                git(api, "branch", branch)
            git(api, "remote", "add", "origin", remote)
            git(api, "push", "-q", "origin", "main", "develop", "qa", "PAY-7", "PAY-8-retry")
            git(api, "remote", "set-url", "origin", "git@github.com:acme/api.git")
            git(api, "fetch", "-q", remote, "+refs/heads/*:refs/remotes/origin/*")
            code, out = run("init_project.py", env={"SDLC_WORKSPACE": ws})
            self.assertEqual(0, code, out)
            draft = json.loads(out[:out.rindex("}") + 1])
        self.assertEqual("Payments API", draft["repos"][0]["role"])
        self.assertEqual(2, len(draft["repos"][0]["onEdit"]))
        self.assertEqual({"host": "github", "org": "acme", "base": "main", "protectedBranches": ["main"],
                          "environments": [{"name": "dev", "branch": "develop"}, {"name": "qa", "branch": "qa"}]},
                         draft["git"])
        self.assertEqual("PAY-\\d+", draft["tickets"]["pattern"])
        self.assertEqual("conventional", draft["commits"]["style"])
        self.assertEqual("npm run seed:users*", draft["realSystems"][0]["command"])


class LauncherTest(unittest.TestCase):
    """`sdlc setup --from <url>` clones the team's ai-sdlc copy, then every repo in its project.json, then runs install.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.remotes = os.path.join(self.root, "remotes")
        self.bare("team-kit", {"scripts/install.py": "print('install ran')\n",
                               "scripts/sdlc.py": "import sys; print('cli', sys.argv[1:])\n",
                               "project.json": json.dumps({"repos": [{"name": "api"}, {"name": "web"}]})})
        for repo in ("api", "web"):
            self.bare(repo, {"README.md": repo})
        self.env = {"SDLC_GIT_BASE": self.remotes + "/", "HOME": self.root, "SDLC_WORKSPACE": None}

    def tearDown(self):
        self.tmp.cleanup()

    def bare(self, name, files):
        work = os.path.join(self.root, "src", name)
        git(self.root, "init", "-q", "-b", "main", work)
        for path, text in files.items():
            write(os.path.join(work, path), text)
        git(work, "add", ".")
        git(work, "commit", "-qm", "init")
        git(self.root, "clone", "-q", "--bare", work, os.path.join(self.remotes, f"{name}.git"))

    def test_setup_then_find_the_workspace(self):
        ws = os.path.join(self.root, "payments")
        os.makedirs(os.path.join(ws, "api", ".git"))  # already there: kept
        code, out = run("launcher.py", "setup", ws, "--from", os.path.join(self.remotes, "team-kit.git"), env=self.env)
        self.assertEqual(0, code, out)
        self.assertIn("have   api", out)
        self.assertIn("clone  web", out)
        self.assertIn("install ran", out)
        os.symlink("team-kit", os.path.join(ws, ".claude"))  # what install.py does
        os.makedirs(os.path.join(ws, "web", "src"))
        self.assertIn("cli ['status']", run("launcher.py", "status", env=self.env, cwd=os.path.join(ws, "web", "src"))[1])

    def test_no_workspace_says_how(self):
        code, out = run("launcher.py", "status", env=self.env, cwd=self.root)
        self.assertNotEqual(0, code)
        self.assertIn("sdlc setup <folder> --from <url>", out)


class ExamplesTest(unittest.TestCase):
    def test_examples_are_valid(self):
        import _hooklib
        folder = os.path.join(KIT, "examples")
        for name in sorted(os.listdir(folder)):
            with open(os.path.join(folder, name)) as f:
                cfg = _hooklib.merged(_hooklib.DEFAULTS, json.load(f))
            self.assertEqual([], _hooklib.validate_config(cfg), name)


class ReferenceTablesTest(unittest.TestCase):
    def test_team_skills_stay_out_of_the_kit_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("ship-ticket", "team-billing"):
                write(os.path.join(tmp, "skills", name, "SKILL.md"), f'---\nname: {name}\ndescription: Does {name}.\n---\n')
            kit = "\n".join(reference_tables.skills(tmp))
            team = "\n".join(reference_tables.TABLES["team-skills"](tmp))
        self.assertIn("`ship-ticket`", kit)
        self.assertNotIn("team-billing", kit)
        self.assertIn("`team-billing`", team)
        self.assertNotIn("ship-ticket", team)

    def test_first_sentence_and_hooks_listed(self):
        self.assertEqual("Runs it, e.g. twice", reference_tables.first_sentence("runs it, e.g. twice. Then more."))
        self.assertEqual([], reference_tables.unlisted_hooks(KIT))


class VersionCheckTest(unittest.TestCase):
    """A copy of version_check.py in a throwaway repo: main at 1.0.0, a branch on top."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self.tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        with open(os.path.join(SCRIPTS, "version_check.py")) as f:
            write(os.path.join(self.repo, "scripts", "version_check.py"), f.read())
        self.release("1.0.0")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "checkout", "-q", "-b", "change")

    def tearDown(self):
        self.tmp.cleanup()

    def release(self, version):
        write(os.path.join(self.repo, "VERSION"), version + "\n")
        write(os.path.join(self.repo, "CHANGELOG.md"), f"# Changelog\n\n## {version} (2026-10-07)\n\n- x\n")

    def check(self):
        p = subprocess.run([sys.executable, os.path.join(self.repo, "scripts", "version_check.py"), "--base", "main"],
                           capture_output=True, text=True)
        return p.returncode, p.stdout

    def commit(self, path):
        write(os.path.join(self.repo, path), "changed\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "change")

    def test_team_files_and_docs_need_no_bump(self):
        for path in ("docs/a.md", "project.json", "PROJECT.md", "skills/team-billing/SKILL.md",
                     "workflows/team-plan.js", "team/scripts/harness.js", "team/templates/pr.md"):
            self.commit(path)
        self.assertEqual(0, self.check()[0])

    def test_kit_change_needs_a_bump(self):
        self.commit("hooks/gates.py")
        code, out = self.check()
        self.assertEqual(1, code)
        self.assertIn("bump VERSION above 1.0.0", out)
        self.release("1.0.1")
        self.commit("hooks/gates.py")
        self.assertEqual(0, self.check()[0])


if __name__ == "__main__":
    unittest.main()
