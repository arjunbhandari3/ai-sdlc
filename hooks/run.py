#!/usr/bin/env python3
"""The one hook entry point registered in settings.json: `run.py <event>`, one process per event.

Runs the hook modules for the event (and tool) in-process, with the event read once, and combines their decisions:
block beats deny beats ask. Renaming, merging or adding a module only changes HOOKS below, never settings.json.

Failure policy: a guard that crashes fails closed (the tool call is denied, with the error); a helper that crashes
fails open (reported on stderr, nothing blocked).
"""
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _hooklib  # noqa: E402

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# event -> [(module, tools it applies to (None = all), "guard" | "helper")]
HOOKS = {
    "session-start": [("session_context", None, "helper")],
    "prompt": [("gates", None, "guard")],
    "pre-tool": [("guard_secrets", FILE_TOOLS | {"Read", "Grep", "Glob", "Bash"}, "guard"),
                 ("guard_shell", {"Bash"}, "guard"),
                 ("gates", FILE_TOOLS | {"Bash"}, "guard")],
    "post-tool": [("after_edit", {"Edit", "Write", "MultiEdit"}, "helper")],
}


def read_event():
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").lstrip("﻿").strip()
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def run_module(name, kind, payload):
    """Run one module's main(); its decisions land in _hooklib._collected."""
    _hooklib._current_hook = name
    sys.argv = [os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")]  # hook mode, not a CLI
    try:
        if os.environ.get("SDLC_HOOK_TEST_CRASH") == name:  # tests only: prove the failure policy
            raise RuntimeError("test crash")
        importlib.import_module(name).main()
    except _hooklib.HookDone:
        pass
    except SystemExit as e:
        if e.code not in (0, None):
            _hooklib._collected.append(("block", f"{name}-exit", f"{name} exited with {e.code}"))
    except _hooklib.ConfigError as exc:  # guards can't judge without the project's rules: fail closed, say why
        if kind == "guard":
            _hooklib._collected.append(("deny", "config-invalid", f"{exc}. Fix it (sdlc validate) before continuing."))
        else:
            print(f"{name}: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - the policy decides what a crash means
        if kind == "guard":
            _hooklib._collected.append(("deny", f"{name}-crashed",
                                        f"The {name} guard crashed ({type(exc).__name__}: {exc}); denied to stay safe. "
                                        "Fix the hook (python3 -m unittest discover -s .claude/hooks/tests)."))
        else:
            print(f"{name} hook failed ({type(exc).__name__}: {exc}); ignored", file=sys.stderr)


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    if event not in HOOKS:
        sys.exit(f"usage: run.py {{{'|'.join(HOOKS)}}}")
    payload = read_event()
    tool = payload.get("tool_name") or ""
    _hooklib._preloaded = payload
    _hooklib._collected = collected = []
    for name, tools, kind in HOOKS[event]:
        if tools is None or tool in tools:
            run_module(name, kind, payload)

    blocks = [reason for d, _, reason in collected if d == "block"]
    if blocks:
        print("\n\n".join(blocks), file=sys.stderr)
        sys.exit(2)
    decisions = [x for x in collected if x[0] in ("deny", "ask")]
    if decisions:
        final = "deny" if any(d == "deny" for d, _, _ in decisions) else "ask"
        reasons = list(dict.fromkeys(r for d, _, r in decisions if d == final or final == "ask"))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": final,
                                                 "permissionDecisionReason": " | ".join(reasons)}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
