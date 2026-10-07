#!/usr/bin/env python3
"""Refresh the generated reference tables in README.md and docs/*.md (skills, agents, scripts, hooks, permissions).

    sdlc docs            rewrite the blocks between <!-- generated:NAME --> markers from the files they describe
    sdlc docs --check    exit 1 if any block is stale or a hook module is missing from docs/guardrails.md (CI)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
import reference_tables  # noqa: E402


def main():
    check = "--check" in sys.argv
    stale = reference_tables.refresh(ROOT, write=not check)
    unlisted = reference_tables.unlisted_hooks(ROOT)
    if unlisted:
        print(f"docs/guardrails.md: add a row for hook module(s) {', '.join(unlisted)} (what they block, what to do)")
    if check:
        if stale:
            print("out of date: " + ", ".join(stale) + " (run sdlc docs)")
        if stale or unlisted:
            sys.exit(1)
        print("docs are up to date")
    else:
        print(f"refreshed {len(stale)} file(s)" + (f": {', '.join(stale)}" if stale else " (all up to date)"))


if __name__ == "__main__":
    main()
