#!/usr/bin/env python3
"""Render the PR status comment body for `.github/workflows/pr-status-comment.yml`.

Called from a `workflow_run` trigger after one of the nine required
workflows completes. Queries the GitHub REST API for the most recent run of
each tracked workflow against the PR head SHA and emits a markdown table
plus a final "ready to merge" or "cannot be merged" line.

Contract
--------
Inputs (environment variables):

    GH_REPO       owner/name of the repository
    PR_NUMBER     pull request number to reference in the trailing line
    HEAD_SHA      head commit SHA of the PR; used to query workflow runs
    GH_TOKEN      GitHub token with `actions: read, contents: read`

Output:
    The markdown body is written to ``stdout`` with a hidden HTML marker at
    the top so that `marocchino/sticky-pull-request-comment` can find and
    update the same comment on every invocation.

Design notes
------------
- We do not `checkout` the PR head. This script runs inside a workflow_run
  handler and only reads metadata from the GitHub API, which is safe
  regardless of PR author.
- ``urllib`` is used in place of a third-party HTTP client so the helper
  has zero non-stdlib dependencies.
- A tracked workflow that has no run yet for the current head SHA is
  reported as ``pending`` rather than blocking the comment. This matches
  the real user experience: comments update as runs complete.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Hidden marker used by marocchino/sticky-pull-request-comment's ``header``
# input. The marker text is arbitrary but must remain stable across runs.
STICKY_HEADER = "bpetite-workflow-status"

# Single source of truth for the tracked-workflow list. Lives next to the
# workflow YAML so a rename/add/remove lands in one place. Loaded lazily so
# the script can be imported for testing without the JSON file present.
TRACKED_JSON = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "tracked-required.json"
)


def _load_tracked() -> list[tuple[str, str]]:
    data = json.loads(TRACKED_JSON.read_text(encoding="utf-8"))
    entries = data.get("tracked")
    if not isinstance(entries, list):
        msg = f"tracked-required.json has no 'tracked' list: {TRACKED_JSON}"
        raise RuntimeError(msg)
    result: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        display = entry.get("display")
        workflow_file = entry.get("workflow_file")
        if isinstance(display, str) and isinstance(workflow_file, str):
            result.append((display, workflow_file))
    if not result:
        msg = f"tracked-required.json has no usable entries: {TRACKED_JSON}"
        raise RuntimeError(msg)
    return result


@dataclass(frozen=True)
class RunResult:
    display: str
    status: str
    conclusion: str | None
    url: str | None
    failing_job: str | None


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.stderr.write(f"missing required environment variable: {name}\n")
        raise SystemExit(1)
    return value


def _gh_request(url: str, token: str) -> dict[str, object]:
    req = urllib.request.Request(url)  # noqa: S310  # GitHub HTTPS API only
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "bpetite-status-comment")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310
            payload = response.read()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"GitHub API error {exc.code} for {url}: {exc.reason}\n")
        raise
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        msg = f"unexpected response shape from {url}: {type(data).__name__}"
        raise RuntimeError(msg)
    return data


def _latest_run(
    repo: str, workflow_file: str, head_sha: str, token: str
) -> dict[str, object] | None:
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow_file}/runs?head_sha={head_sha}&per_page=1"
    )
    data = _gh_request(url, token)
    runs = data.get("workflow_runs") or []
    if not isinstance(runs, list) or not runs:
        return None
    run = runs[0]
    if not isinstance(run, dict):
        return None
    return run


def _first_failing_job(repo: str, run_id: int, token: str) -> str | None:
    url = (
        f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
        f"?filter=latest&per_page=50"
    )
    data = _gh_request(url, token)
    jobs = data.get("jobs") or []
    if not isinstance(jobs, list):
        return None
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("conclusion") == "failure":
            name = job.get("name")
            if isinstance(name, str):
                return name
    return None


def _collect(repo: str, head_sha: str, token: str) -> list[RunResult]:
    results: list[RunResult] = []
    for display, workflow_file in _load_tracked():
        run = _latest_run(repo, workflow_file, head_sha, token)
        if run is None:
            results.append(RunResult(display, "pending", None, None, None))
            continue
        status = str(run.get("status") or "unknown")
        conclusion = run.get("conclusion")
        conclusion_str = conclusion if isinstance(conclusion, str) else None
        url = run.get("html_url")
        url_str = url if isinstance(url, str) else None
        failing_job: str | None = None
        run_id = run.get("id")
        if conclusion_str == "failure" and isinstance(run_id, int):
            try:
                failing_job = _first_failing_job(repo, run_id, token)
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError):
                failing_job = None
        results.append(RunResult(display, status, conclusion_str, url_str, failing_job))
    return results


def _status_cell(result: RunResult) -> str:
    if result.status != "completed":
        return result.status
    return result.conclusion or "unknown"


def _comment_cell(result: RunResult) -> str:
    if result.status != "completed":
        return "waiting"
    conclusion = result.conclusion or "unknown"
    if conclusion == "success":
        return "ok"
    if conclusion in {"skipped", "cancelled", "neutral"}:
        return conclusion
    # Failure of some kind.
    parts: list[str] = []
    if result.failing_job:
        parts.append(f"job `{result.failing_job}`")
    if result.url:
        parts.append(f"[run]({result.url})")
    if not parts:
        parts.append("see run logs")
    return " - ".join(parts)


def _final_line(pr_number: str, results: list[RunResult]) -> str:
    """Render the trailing status line.

    Deliberately worded as a snapshot of the tracked workflow list, not a
    merge verdict. Branch protection is the authoritative gate; this comment
    only reports whether every tracked workflow has finished and what its
    terminal state was. A reviewer should never rely on "ready" wording to
    substitute for checking branch protection.
    """
    any_failed = any(
        r.conclusion not in (None, "success", "skipped", "neutral")
        and r.status == "completed"
        for r in results
    )
    all_done = all(r.status == "completed" for r in results)
    all_green = all_done and all(
        r.conclusion in ("success", "skipped", "neutral") for r in results
    )
    if any_failed:
        return (
            f"PR #{pr_number}: one or more tracked workflows failed. "
            "Branch protection will block merge until they go green."
        )
    if all_green:
        return (
            f"PR #{pr_number}: all tracked workflows are green. "
            "Merge readiness is still subject to branch protection rules."
        )
    return f"PR #{pr_number}: tracked workflows are still running."


def render(pr_number: str, results: list[RunResult]) -> str:
    lines: list[str] = []
    lines.append(f"<!-- sticky-comment:{STICKY_HEADER} -->")
    lines.append("")
    lines.append("## bpetite workflows")
    lines.append("")
    lines.append("| Workflow | Status | Comment if failure and where |")
    lines.append("| --- | --- | --- |")
    lines.extend(
        f"| {result.display} | {_status_cell(result)} | {_comment_cell(result)} |"
        for result in results
    )
    lines.append("")
    lines.append(_final_line(pr_number, results))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    repo = _require_env("GH_REPO")
    pr_number = _require_env("PR_NUMBER")
    head_sha = _require_env("HEAD_SHA")
    token = _require_env("GH_TOKEN")

    results = _collect(repo, head_sha, token)
    sys.stdout.write(render(pr_number, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
