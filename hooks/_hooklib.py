"""Shared helpers for the ai-sdlc's Claude Code hooks, and the project config they read (project.json).

Each hook reads the hook event JSON on stdin. To block a call it either exits 2 with a reason on
stderr (block) or prints a PreToolUse decision (deny / ask) as JSON (decide / emit). An uncaught
error exits 1, which Claude Code reports but does not treat as a block.

Audit log: every block/deny/ask is appended to ~/.claude/logs/tool_audit.jsonl (override with
SDLC_HOOK_LOG) by hook and rule id. Never logged: command text, file contents, search patterns, tool results,
reason text. Data-file names (which can contain people's names) are reduced to their folder.
"""
import copy
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone

WORKSPACE = os.environ.get("SDLC_WORKSPACE") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)  # <workspace>/.claude/<dir>/<file>; SDLC_WORKSPACE overrides (tests, unusual layouts)
# ai-sdlc itself: <workspace>/.claude when linked, or wherever it's cloned (CI); tests point SDLC_WORKSPACE elsewhere
CLAUDE = os.path.join(WORKSPACE, ".claude") if os.environ.get("SDLC_WORKSPACE") else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
TICKETS = os.environ.get("SDLC_TICKETS") or os.path.join(WORKSPACE, ".sdlc", "tickets")  # personal state, not in a repo
SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "\n", ";;"}

_payload = {}


# --- project config (project.json) -------------------------------------------

DEFAULTS = {
    "name": "",
    "repos": [],
    "git": {"host": "github", "org": "", "protectedBranches": ["main", "master"], "environments": []},
    "tickets": {"tracker": "none", "pattern": "[A-Z][A-Z0-9]+-\\d+", "envBranch": "{ticket}-{env}"},
    "commits": {"style": "ticket", "maxSubjectLength": 72, "forbidAiMentions": True},
    "data": {"sensitivity": "none", "dataFiles": [".csv", ".xlsx", ".xls", ".pdf"]},
    "realSystems": [],
}
SENSITIVITY = {"phi": "patient data (PHI)", "pii": "personal data (PII)", "financial": "financial data",
               "none": "real data"}
COMMIT_STYLES = {"ticket", "conventional", "none"}
_config = None


class ConfigError(Exception):
    """project.json is unreadable or invalid; guards fail closed on it."""


def merged(defaults, override):
    out = copy.deepcopy(defaults)
    for k, v in (override or {}).items():
        out[k] = merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def validate_config(cfg):
    """Problems in a project.json, as readable strings (empty = valid)."""
    errors = []
    names = [r.get("name") for r in cfg["repos"] if isinstance(r, dict)]
    if len(names) != len(cfg["repos"]) or not all(isinstance(n, str) and n and "/" not in n for n in names):
        errors.append("repos must be objects with a folder 'name' (no slashes)")
    if len(set(names)) != len(names):
        errors.append("repo names must be unique")
    try:
        re.compile(cfg["tickets"]["pattern"])
    except (re.error, TypeError):
        errors.append("tickets.pattern must be a regular expression")
    if cfg["commits"].get("style") not in COMMIT_STYLES:
        errors.append(f"commits.style must be one of {sorted(COMMIT_STYLES)}")
    if cfg["data"].get("sensitivity") not in SENSITIVITY:
        errors.append(f"data.sensitivity must be one of {sorted(SENSITIVITY)}")
    if not isinstance(cfg["git"].get("protectedBranches"), list):
        errors.append("git.protectedBranches must be a list of branch names")
    for i, env in enumerate(cfg["git"].get("environments") or []):
        if not isinstance(env, dict) or not env.get("name") or not env.get("branch"):
            errors.append(f"git.environments[{i}] needs a name and a branch")
    for i, rule in enumerate(cfg["realSystems"]):
        if not isinstance(rule, dict) or not rule.get("command") or not rule.get("reason"):
            errors.append(f"realSystems[{i}] needs a command pattern and a reason")
    return errors


def config():
    """project.json merged over DEFAULTS (cached). Missing file -> defaults; invalid -> ConfigError."""
    global _config
    if _config is None:
        path = os.path.join(CLAUDE, "project.json")
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as e:
            raise ConfigError(f"project.json can't be read: {e}")
        cfg = merged(DEFAULTS, raw)
        errors = validate_config(cfg)
        if errors:
            raise ConfigError("project.json is invalid: " + "; ".join(errors))
        _config = cfg
    return _config


def protected_branches():
    return set(config()["git"]["protectedBranches"]) | {e["branch"] for e in config()["git"].get("environments", [])}


def ticket_re():
    return re.compile(rf"\b({config()['tickets']['pattern']})\b")


def branch_ticket_key(branch):
    """The ticket a branch belongs to: PAY-12, PAY-12-qa, PAY-12-add-filter -> PAY-12; else None."""
    m = re.match(rf"({config()['tickets']['pattern']})(?:-|$)", branch or "")
    return m.group(1) if m else None


def repo_config(name):
    return next((r for r in config()["repos"] if r["name"] == name), {})


def sensitive_data():
    return SENSITIVITY[config()["data"]["sensitivity"]]


# --- hook I/O --------------------------------------------------------------

class HookInput:
    def __init__(self, data):
        data = data if isinstance(data, dict) else {}
        self.data = data
        self.cwd = data.get("cwd") or os.getcwd()
        self.tool_name = data.get("tool_name") or ""
        self.tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        self.command = self.tool_input.get("command") or ""
        self.file_path = (
            self.tool_input.get("file_path")
            or self.tool_input.get("notebook_path")
            or self.tool_input.get("path")
            or ""
        )


# Dispatcher mode (run.py): the event is read once, and block/emit collect decisions instead of exiting, so every
# guard for the event runs and run.py combines them. Standalone runs (and the tests) behave as before.
_preloaded = None
_collected = None
_current_hook = None


class HookDone(Exception):
    """A hook finished its decision in dispatcher mode."""


def read_input():
    global _payload
    if _preloaded is not None:
        _payload = _preloaded
        return HookInput(_payload)
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").lstrip("﻿").strip()
    try:
        _payload = json.loads(raw) if raw else {}
    except ValueError:
        _payload = {}
    return HookInput(_payload)


def _hook_name():
    return _current_hook or os.path.splitext(os.path.basename(sys.argv[0]))[0]


def block(reason, rule=None):
    append_log({**base_entry(_payload), "kind": "guard", "guard": _hook_name(), "decision": "block", "rules": [rule or "block"]})
    if _collected is not None:
        _collected.append(("block", rule or "block", reason))
        raise HookDone
    print(reason, file=sys.stderr)
    sys.exit(2)


def decide(decision, reason, rule=None):
    emit([(decision, rule or decision, reason)])


def emit(decisions):
    """decisions: [(deny|ask, rule_id, reason)]. deny wins over ask. Exits (or, under run.py, hands them back)."""
    if _collected is not None:
        if decisions:
            final = "deny" if any(d == "deny" for d, _, _ in decisions) else "ask"
            append_log({**base_entry(_payload), "kind": "guard", "guard": _hook_name(), "decision": final,
                        "rules": sorted({r for _, r, _ in decisions})})
            _collected.extend(decisions)
        raise HookDone
    if not decisions:
        sys.exit(0)
    final = "deny" if any(d == "deny" for d, _, _ in decisions) else "ask"
    reasons, rules = [], []
    for d, rule, reason in decisions:
        if d == final or final == "ask":
            if reason not in reasons:
                reasons.append(reason)
        if rule not in rules:
            rules.append(rule)
    append_log({**base_entry(_payload), "kind": "guard", "guard": _hook_name(), "decision": final, "rules": rules})
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": final,
        "permissionDecisionReason": " | ".join(reasons),
    }}))
    sys.exit(0)


def in_workspace(path):
    return bool(path) and os.path.abspath(os.path.expanduser(path)).startswith(WORKSPACE)


def repo_of(path):
    """(name, folder) of the workspace repo holding path (not .claude), else (None, None)."""
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(WORKSPACE))
    top = rel.split(os.sep)[0]
    if rel.startswith("..") or top in (".claude", ".sdlc") or not os.path.isdir(os.path.join(WORKSPACE, top, ".git")):
        return None, None
    return top, os.path.join(WORKSPACE, top)


def run(args, cwd=None, timeout=10):
    """Run a command and return (returncode, combined output); (-1, error) if it can't start."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def git_out(repo_dir, *args, timeout=10):
    """stdout of `git -C repo_dir args...`, or None on failure."""
    try:
        p = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def current_branch(repo_dir):
    return (git_out(repo_dir, "branch", "--show-current", timeout=5) or "").strip()


def upstream_branch(repo_dir):
    """'lf-develop' for a branch tracking origin/lf-develop, else None."""
    out = (git_out(repo_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", timeout=5) or "").strip()
    return out.split("/", 1)[1] if "/" in out else None


# --- shell command parsing -------------------------------------------------

def tokenize(command):
    """Split a shell command into words, with operators (;, &&, |, newline...) as their own tokens."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes, e.g. inside an unquoted heredoc body
        return re.findall(r"&&|\|\||[;&|()\n]|[^\s;&|()]+", command)


def segments(command):
    """Yield each simple command (list of words) in a compound shell command, minus leading
    VAR=value assignments and sudo/command/exec wrappers."""
    current = []
    for tok in tokenize(command) + [";"]:
        if tok in SEPARATORS:
            while current and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", current[0]) or current[0] in ("sudo", "command", "exec")):
                current = current[1:]
            if current:
                yield current
            current = []
        else:
            current.append(tok)


def resolve(base, path):
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))


def program(word):
    return os.path.basename(word).lower()


def commands(command, cwd):
    """Yield (words, dir) for each simple command, tracking `cd`/`pushd` so dir is where it runs."""
    here = cwd
    for words in segments(command):
        if program(words[0]) in ("cd", "pushd") and len(words) > 1:
            here = resolve(here, words[1])
            continue
        yield words, here


class GitCall:
    def __init__(self, repo_dir, sub, args):
        self.dir = repo_dir
        self.sub = sub
        self.args = args


GIT_OPTS_WITH_VALUE = {"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def parse_git(words, here):
    """GitCall for a `git [-C dir] <sub> ...` command, else None."""
    if program(words[0]) != "git":
        return None
    repo_dir, i = here, 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            repo_dir = resolve(repo_dir, words[i + 1])
            i += 2
        elif words[i] in GIT_OPTS_WITH_VALUE:
            i += 2
        else:
            i += 1
    return GitCall(repo_dir, words[i], words[i + 1:]) if i < len(words) else None


def git_calls(command, cwd):
    for words, here in commands(command, cwd):
        call = parse_git(words, here)
        if call:
            yield call


# --- secrets and sensitive files --------------------------------------------

HIGH_SECRETS = [
    ("AWS access key ID", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("AWS secret access key", re.compile(r"aws_?secret_?access_?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+]{40}", re.I)),
    ("Private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("Slack token", re.compile(r"xox[abprs]-[0-9A-Za-z-]{10,}")),
    ("Slack webhook URL", re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]{6,}/B[A-Z0-9]{6,}/[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,}")),
    ("Atlassian/Bitbucket token", re.compile(r"(?:ATBB|ATATT)[A-Za-z0-9_=.-]{20,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("Stripe live key", re.compile(r"(?:sk|rk)_live_[0-9A-Za-z]{20,}")),
    ("SendGrid key", re.compile(r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Twilio key", re.compile(r"SK[0-9a-f]{32}")),
]
# Connection strings with an inline password (mongodb, redis, postgres, mysql, amqp, sftp...).
CONN = re.compile(r"(?:mongodb(?:\+srv)?|rediss?|postgres(?:ql)?|mysql|amqps?|s?ftp)://[^:/@\s\"'`]+:([^@\s\"'`]+)@", re.I)
# Values that are clearly placeholders or test fixtures.
PLACEHOLDER = re.compile(
    r"\$\{|^\$[A-Za-z_]|\{\{|<[^>]*>|\*\*\*|x{4,}|your[_-]|change[_-]?me|example|placeholder|dummy|fake|mock"
    r"|sample|test|redacted|password|passwd|secret|^pass$|^pwd$|^user$",
    re.I,
)


def find_secrets(text):
    """[(label, [up to 3 matches, connection strings pre-redacted])] of high-confidence credentials."""
    if not text:
        return []
    found = []
    for label, pattern in HIGH_SECRETS:
        matches = [m.group(0) for m in pattern.finditer(text)][:3]
        if matches:
            found.append((label, matches))
    conns = [m.group(0) for m in CONN.finditer(text) if not PLACEHOLDER.search(m.group(1))][:3]
    if conns:
        found.append(("Connection string with password", [c.split("://")[0] + "://…@" for c in conns]))
    return found


KEY_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk"}
KEY_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
ENV_TEMPLATE = re.compile(r"example|sample|template|dist", re.I)


def data_extensions():
    try:
        return {e.lower() for e in config()["data"]["dataFiles"]}
    except ConfigError:
        return set(DEFAULTS["data"]["dataFiles"])


def is_env_file(path):
    name = os.path.basename(path).lower()
    return name == ".env" or name.startswith((".env.", ".env-")) or name.endswith(".env")


def classify_path(path):
    """(deny|ask, description) for files that must not be committed casually, else None."""
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    if is_env_file(path):
        return None if ENV_TEMPLATE.search(name) else ("deny", "an environment file with secrets")
    if ext in KEY_EXTENSIONS or name in KEY_NAMES:
        return ("deny", "a private key or certificate")
    if ext in data_extensions():
        return ("ask", f"a data file that may contain {sensitive_data()}")
    return None


# --- audit log -------------------------------------------------------------

SUBCOMMAND_TOOLS = {"npm", "npx", "yarn", "pnpm", "aws", "docker", "kubectl", "pip", "pip3", "gh", "terraform", "sam", "claude"}
SAFE_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9:_.-]{0,40}$")


def log_path():
    return os.environ.get("SDLC_HOOK_LOG") or os.path.expanduser("~/.claude/logs/tool_audit.jsonl")


def append_log(entry):
    """Append one JSON line to the audit log. Rotates to .1 past 20 MB. Never raises."""
    path = log_path()
    try:
        import fcntl

        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **entry},
                          ensure_ascii=False, default=str) + "\n"
        max_bytes = int(os.environ.get("SDLC_HOOK_LOG_MAX_BYTES", 20 * 1024 * 1024))
        # Parallel tool calls run hooks concurrently; the lock keeps lines whole.
        with open(path + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if os.path.exists(path) and os.path.getsize(path) > max_bytes:
                    os.replace(path, path + ".1")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except Exception as exc:
        try:
            with open(os.path.join(os.path.dirname(path), "hook_errors.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} {exc!r}\n")
        except OSError:
            pass


def base_entry(payload):
    keys = {"hook_event_name": "event", "session_id": "session_id", "tool_use_id": "tool_use_id",
            "tool_name": "tool", "cwd": "cwd", "permission_mode": "permission_mode", "agent_type": "agent_type"}
    return {short: payload[key] for key, short in keys.items() if payload.get(key) is not None}


def safe_path(path):
    """Data-file names can contain people's names, so log only their folder and extension."""
    if not path:
        return None
    ext = os.path.splitext(str(path))[1].lower()
    return f"{os.path.dirname(str(path))}/*{ext}" if ext in data_extensions() else str(path)


def summarize_command(command):
    """'git push origin main && npm run lint' -> 'git push; npm run lint'. Programs and
    subcommands only: arguments, messages, URLs and paths are dropped."""
    parts = []
    for words in segments(command):
        prog, rest = program(words[0]), words[1:]
        if prog == "git":
            call = parse_git(words, "")
            part = f"git {call.sub}" if call and SAFE_WORD.match(call.sub) else "git"
        elif prog in ("python", "python3", "node", "nodemon"):
            script = next((a for a in rest if not a.startswith("-")), None)
            part = f"{prog} {os.path.basename(script)}" if script and SAFE_WORD.match(os.path.basename(script)) else prog
        elif prog in SUBCOMMAND_TOOLS:
            words2 = [w for w in rest if not w.startswith("-")][:2]
            words2 = [w for w in words2 if SAFE_WORD.match(w)]
            part = " ".join([prog] + (words2 if prog in ("npm", "yarn", "pnpm", "aws") else words2[:1]))
        else:
            part = prog if SAFE_WORD.match(prog) else "?"
        parts.append(part)
    return "; ".join(parts)[:300]


def summarize(tool_name, ti):
    """A short description of what a tool call touched, without data that could identify a person."""
    if tool_name == "Bash":
        return summarize_command(ti.get("command") or "")
    if tool_name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return safe_path(ti.get("file_path") or ti.get("notebook_path"))
    if tool_name == "Glob":
        return (ti.get("pattern") or "")[:120]
    if tool_name == "Grep":  # never the search pattern: it can be a person's name
        return safe_path(ti.get("path")) or "(cwd)"
    if tool_name == "WebFetch":
        m = re.match(r"^https?://([^/:?#]+)", ti.get("url") or "")
        return m.group(1) if m else None
    if tool_name in ("Agent", "Task"):
        return ti.get("subagent_type")
    if tool_name == "Skill":
        return ti.get("skill")
    return None
