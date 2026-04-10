#!/usr/bin/env python3
"""Classify PR changed files against a glob list for required CI workflows.

Consumed by the ``.github/actions/detect-changes`` composite action. Written
in stdlib Python so the action is portable to every runner image GitHub
provides, including macOS hosts that ship Bash 3.2 and lack ``mapfile`` and
``shopt -s globstar``.

Contract
--------
Inputs are read from environment variables to avoid any shell-escaping
surface around user-supplied glob lists:

    INPUT_GLOBS        newline-delimited list of glob patterns
    GITHUB_EVENT_NAME  the GitHub Actions event name
    PR_BASE_SHA        pull_request.base.sha (required for pull_request)
    PR_HEAD_SHA        pull_request.head.sha (required for pull_request)
    GITHUB_OUTPUT      path to the step output file (supplied by Actions)

Outputs written to ``GITHUB_OUTPUT``:

    relevant           "true" or "false"
    changed_count      total number of files in the diff range

Non-``pull_request`` events (push, schedule, workflow_dispatch, workflow_run)
always resolve to ``relevant=true`` so the main-branch sweep and manual
runs never no-op accidentally.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import PurePosixPath


def _emit(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        sys.stderr.write("GITHUB_OUTPUT is not set; cannot emit step outputs\n")
        raise SystemExit(1)
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.stderr.write(f"missing required environment variable: {name}\n")
        raise SystemExit(1)
    return value


def _git_fetch(sha: str) -> None:
    """Best-effort fetch of a commit SHA. Failure is non-fatal.

    actions/checkout for pull_request events materializes a merge commit
    but neither the PR base nor the PR head are guaranteed to be reachable
    in local history. GitHub's git server permits fetch-by-sha, so a shallow
    fetch with depth 1 is enough to resolve the diff. If the object is
    already present the extra fetch is a no-op.
    """
    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", sha],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _changed_files(base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _parse_patterns(raw: str) -> list[str]:
    patterns: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _matches_any(path: str, patterns: list[str]) -> bool:
    """Return True if ``path`` matches any glob.

    Uses Python's ``fnmatch`` for single-segment matching and a manual
    prefix match for ``**`` recursive patterns so the semantics are identical
    on every runner.
    """
    posix = PurePosixPath(path).as_posix()
    for pattern in patterns:
        if "**" in pattern:
            # Split around the first ** token and require the parts to
            # match a prefix and (optionally) a suffix of the path.
            prefix, _, remainder = pattern.partition("**")
            prefix = prefix.rstrip("/")
            if prefix and not posix.startswith(f"{prefix}/") and posix != prefix:
                continue
            suffix = remainder.lstrip("/")
            if not suffix:
                return True
            if fnmatch.fnmatchcase(posix, f"{prefix}/{suffix}") or posix.endswith(
                f"/{suffix}"
            ):
                return True
            # Fall back: try matching the suffix against the tail segments.
            if fnmatch.fnmatchcase(posix.rsplit("/", 1)[-1], suffix):
                return True
        elif fnmatch.fnmatchcase(posix, pattern):
            return True
    return False


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    if event != "pull_request":
        sys.stdout.write(
            f"Non pull_request event ({event or 'unknown'}); treating as relevant.\n"
        )
        _emit("relevant", "true")
        _emit("changed_count", "-1")
        return 0

    base_sha = _require_env("PR_BASE_SHA")
    head_sha = _require_env("PR_HEAD_SHA")
    raw_globs = _require_env("INPUT_GLOBS")

    patterns = _parse_patterns(raw_globs)
    if not patterns:
        sys.stderr.write("no glob patterns supplied\n")
        return 1

    _git_fetch(base_sha)
    _git_fetch(head_sha)

    try:
        changed = _changed_files(base_sha, head_sha)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"git diff failed: {exc.stderr}\n")
        return 1

    _emit("changed_count", str(len(changed)))

    if not changed:
        sys.stdout.write(f"No files changed between {base_sha} and {head_sha}.\n")
        _emit("relevant", "false")
        return 0

    sys.stdout.write(f"Changed files ({len(changed)}):\n")
    for path in changed:
        sys.stdout.write(f"  {path}\n")
    sys.stdout.write("\n")

    matched = [path for path in changed if _matches_any(path, patterns)]
    if matched:
        sys.stdout.write(f"Matched {len(matched)} files against supplied globs:\n")
        for path in matched:
            sys.stdout.write(f"  {path}\n")
        _emit("relevant", "true")
    else:
        sys.stdout.write(
            "No changed file matched any supplied glob; heavy job will no-op.\n"
        )
        _emit("relevant", "false")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
