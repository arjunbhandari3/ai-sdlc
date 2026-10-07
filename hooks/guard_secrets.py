#!/usr/bin/env python3
"""PreToolUse(Read|Edit|Write|MultiEdit|NotebookEdit|Grep|Glob|Bash): keep secrets out of reach.

1. Paths and commands: block reading or writing secret files (env files, keys, cloud/registry credentials)
   and commands that dump environment variables or fetch secrets.
2. Content about to be written or run (Write/Edit/MultiEdit/NotebookEdit/Bash): high-confidence credential
   formats are blocked; likely-but-uncertain ones (JWTs, Bearer tokens, literal passwords) ask the user.
   Matches are shown redacted.
"""
import re

from _hooklib import PLACEHOLDER, block, decide, find_secrets, read_input

# Safe mentions: example env files, and process.env / import.meta.env in code or regex-escaped
# in search patterns (process\.env).
SAFE = re.compile(r"\.env\.(example|sample|template)|(process|meta)\\?\.env")
# `.env` not preceded or followed by an identifier char, so dotenv / .envrc are fine.
ENV_FILE = re.compile(r"(?<![A-Za-z0-9_])\.env(?![A-Za-z0-9_])")
SECRET_FILE = re.compile(
    r"(\.pem|\.key|\.p12|\.pfx|\.jks|\.keystore|id_rsa|id_ed25519|id_ecdsa|\.ppk)(?![A-Za-z0-9_.])"
    r"|\.aws/(credentials|config)|\.npmrc|\.netrc|\.pgpass|\.docker/config\.json|\.git-credentials"
    r"|\.ssh/|secrets?\.(json|ya?ml)(?![A-Za-z0-9_])|credentials\.json",
    re.I,
)

SEP = r"(?:^|[;&|(`]|\$\()\s*"
BASH_RULES = [
    (re.compile(SEP + r"(env|set|export\s+-p|declare\s+-x)\s*($|[|;&>)])", re.M),
     "dumping environment variables can expose secrets."),
    (re.compile(SEP + r"printenv(\s|$)", re.M), "printenv can expose secrets."),
    (re.compile(r"(echo|printf|print|console\.log)[^|;&]*\$\{?[A-Z0-9_]*(SECRET|TOKEN|PASSWORD|PASSWD|PASS|API_?KEY|PRIVATE|CREDENTIAL|MONGO|DB_URI|DATABASE_URL|CONNECTION)", re.I),
     "printing a secret-named variable."),
    # Printing the whole environment (passing it on, e.g. {**os.environ, ...} or {...process.env}, is fine).
    (re.compile(r"(console\.(log|dir|error|info)|print|pprint|dumps|JSON\.stringify)\s*\(\s*(dict\()?(process\.env|os\.environ)\s*\)", re.I),
     "printing the whole process environment."),
    (re.compile(r"aws\s+(secretsmanager\s+get-secret-value|ssm\s+get-parameters?(\s|$).*--with-decryption|configure\s+(get|export-credentials|list)|sts\s+get-session-token)", re.I),
     "fetching secrets from AWS."),
    # Inline scripts that call Secrets Manager (plain code searches for the name are fine).
    (re.compile(r"(node|npx|python3?)[^|;&]*\s(-e|--eval|-p|-c)\s[^|;&]*(GetSecretValue|get_secret_value)", re.I),
     "fetching secrets from AWS Secrets Manager."),
]


# --- content scan ------------------------------------------------------------

JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{30,}")
LITERAL = re.compile(
    r"(password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token|client[_-]?secret"
    r"|private[_-]?key|secret[_-]?key)[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']",
    re.I,
)
TEST_FILE = re.compile(r"(/tests?/|/__tests__/|\.(spec|test)\.[jt]sx?$)")


def redact(s, keep=6):
    return s if s.endswith("…@") else s[:keep] + "…"


def content(hook):
    ti = hook.tool_input
    parts = [ti.get("content"), ti.get("new_string"), ti.get("new_source"), ti.get("command")]
    parts += [e.get("new_string") for e in ti.get("edits") or [] if isinstance(e, dict)]
    return "\n".join(p for p in parts if isinstance(p, str))


# --- paths and commands ----------------------------------------------------

def target(hook):
    ti = hook.tool_input
    if hook.tool_name == "Bash":
        return hook.command
    if hook.tool_name in ("Grep", "Glob"):
        return " ".join(str(ti[k]) for k in ("path", "pattern", "glob") if ti.get(k))
    return hook.file_path


def deny(why, rule):
    block(f"Blocked: {why} Use .env.example for variable names, or ask the user to do this themselves.", rule)


def check_paths(hook):
    text = target(hook)
    if not text:
        return
    stripped = SAFE.sub("", text)
    if ENV_FILE.search(stripped):
        deny(".env files hold live secrets and must not be read or modified.", "env-file")
    if SECRET_FILE.search(text):
        deny("this looks like a key or credentials file.", "secret-file")
    if hook.tool_name == "Bash":
        for pattern, why in BASH_RULES:
            if pattern.search(text):
                deny(why, "env-dump-or-secret-fetch")


def scan_content(hook):
    text = content(hook)
    if not text:
        return

    high = find_secrets(text)
    if high:
        lines = [f"- {label}: {', '.join(redact(m) for m in matches)}" for label, matches in high]
        block(
            "Blocked: this would write a real-looking secret into a file or command:\n"
            + "\n".join(lines)
            + "\nLoad it at runtime instead (an env var documented in .env.example, or the project's secret store).",
            "write-secret",
        )

    # Test fixtures legitimately contain fake tokens/passwords; only high-confidence formats apply there.
    if TEST_FILE.search(hook.file_path):
        return

    medium = []
    for label, pattern in (("JWT", JWT), ("Bearer token", BEARER)):
        found = [m.group(0) for m in pattern.finditer(text)][:3]
        if found:
            medium.append(f"{label}: {', '.join(redact(f) for f in found)}")
    literals = [m for m in LITERAL.finditer(text) if not PLACEHOLDER.search(m.group(2))][:3]
    if literals:
        medium.append("Hardcoded credential value: " + ", ".join(f"{m.group(1)}=\"{redact(m.group(2), 3)}\"" for m in literals))
    if medium:
        decide("ask", f"Possible secret in content: {'; '.join(medium)}. Approve only if this is a fake/test value.", "possible-secret")


def main():
    hook = read_input()
    check_paths(hook)   # blocks (exits) on a secret path or command
    scan_content(hook)  # blocks or asks on secret-looking content


if __name__ == "__main__":
    main()
