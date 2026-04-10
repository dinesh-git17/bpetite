#!/bin/bash
#
# Staged commit workflow for bpetite.
#
# Stages every change (`git add -A`) first, then shows the EXACT staged
# diff, then asks for approval over that diff, then writes the sentinel
# and commits. This guarantees the approval event certifies the actual
# content of the resulting commit: no path can enter the commit after the
# human has approved the diff.
#
# Writes .git/COMMIT_APPROVED just before invoking `git commit` and removes
# it on exit via a trap. The repo-local `require-commitall-approval`
# pre-commit hook blocks any commit attempted without this sentinel in
# place, so every Claude-authored commit must go through this script (or
# the /commitall slash command that wraps it).
#
# Usage: bash scripts/commitall.sh
#
set -e

SENTINEL=".git/COMMIT_APPROVED"

cleanup() {
  rm -f "$SENTINEL"
}
trap cleanup EXIT

# Stage everything first so the approval prompt reflects the exact set
# of changes that will enter the commit. Nothing new can be introduced
# between the approval step and the commit itself.
git add -A

if git diff --cached --quiet; then
  echo ""
  echo "[ABORT] Nothing staged. Working tree is clean."
  exit 1
fi

echo ""
echo "=== Git Status (post-stage) ==="
git status

echo ""
echo "=== Staged Diff Summary ==="
git diff --cached --stat

echo ""
read -r -p "Commit message: " COMMIT_MSG

if [ -z "$COMMIT_MSG" ]; then
  echo "[ABORT] Commit message cannot be empty."
  exit 1
fi

echo ""
read -r -p "Approve this commit? [y/N] " APPROVAL

if [[ "$APPROVAL" != "y" && "$APPROVAL" != "Y" ]]; then
  echo "[ABORT] Commit not approved."
  exit 1
fi

touch "$SENTINEL"
git commit -m "$COMMIT_MSG"

echo ""
echo "[OK] Commit complete."
