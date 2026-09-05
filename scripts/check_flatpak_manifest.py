#!/usr/bin/env python3
"""Validate Vibelight's Flatpak sandbox and source-pin contracts."""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "vibelight.json"
SOURCE_URL = "https://github.com/xenstalker02/Vibelight.git"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def without_source_pin(data: dict) -> dict:
    """Ignore only our source commit when checking a pin-only update."""
    normalized = copy.deepcopy(data)
    sources = [
        source
        for module in normalized.get("modules", [])
        for source in module.get("sources", [])
        if source.get("url") == SOURCE_URL
    ]
    if len(sources) != 1 or "commit" not in sources[0]:
        fail("pin-only comparison requires exactly one committed Vibelight source")
    sources[0]["commit"] = None
    return normalized


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    finish_args = data.get("finish-args", [])

    if "--device=all" in finish_args:
        fail("Flatpak manifest still grants all host devices")
    for required in ("--device=dri", "--device=input"):
        if required not in finish_args:
            fail(f"Flatpak manifest is missing {required}")

    sources = [
        source
        for module in data.get("modules", [])
        for source in module.get("sources", [])
        if source.get("url") == SOURCE_URL
    ]
    if len(sources) != 1:
        fail(f"expected exactly one Vibelight source, found {len(sources)}")

    source_pin = sources[0].get("commit", "")
    if not isinstance(source_pin, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", source_pin):
        fail("Vibelight source pin must be a full 40-character hexadecimal commit hash")

    git("cat-file", "-e", f"{source_pin}^{{commit}}")
    git("merge-base", "--is-ancestor", source_pin, "HEAD")
    commits_behind = int(git("rev-list", "--count", f"{source_pin}..HEAD"))
    if commits_behind > 1:
        fail(
            f"Vibelight source pin is {commits_behind} commits behind HEAD; "
            "it may only trail by the pin-only commit"
        )

    if commits_behind == 1:
        changed = git("diff", "--no-ext-diff", "--name-only", "--no-renames", source_pin, "HEAD").splitlines()
        if changed != ["vibelight.json"]:
            fail("the commit after the source pin must change only vibelight.json")
        previous = json.loads(git("show", f"{source_pin}:vibelight.json"))
        committed = json.loads(git("show", "HEAD:vibelight.json"))
        if without_source_pin(previous) != without_source_pin(committed):
            fail("the commit after the source pin changes manifest content beyond the source pin")
        if data != committed:
            fail("working manifest differs from the committed pin-only manifest")

    print("PASS: Flatpak manifest permissions and source pin are current")


if __name__ == "__main__":
    main()
