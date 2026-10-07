"""Shared bits for the Python scripts: where things are, and the project config (read through hooks/_hooklib.py, so the
scripts and the guards always agree). Standard library only."""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ai-sdlc (= <workspace>/.claude)
WORKSPACE = os.environ.get("SDLC_WORKSPACE") or os.path.dirname(REPO)
sys.path.insert(0, os.path.join(REPO, "hooks"))
import _hooklib  # noqa: E402

# Personal ticket state lives in the workspace, outside every repo (SDLC_TICKETS overrides it, e.g. in tests)
TICKETS = _hooklib.TICKETS
ConfigError = _hooklib.ConfigError


def project():
    """project.json merged over the defaults; raises ConfigError if invalid."""
    return _hooklib.config()


def repo_names():
    return [r["name"] for r in project()["repos"]]


def ticket_key(branch):
    """The ticket folder for a branch: PAY-12, PAY-12-qa, PAY-12-add-filter -> PAY-12; other branches keep their name."""
    try:
        key = _hooklib.branch_ticket_key(branch)
    except ConfigError:
        key = None
    return key or re.sub(r"[^\w.-]+", "_", branch)


def is_ticket(name):
    try:
        return bool(re.fullmatch(project()["tickets"]["pattern"], name))
    except ConfigError:
        return False
