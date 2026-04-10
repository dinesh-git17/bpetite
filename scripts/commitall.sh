#!/bin/bash
#
# Staged commit workflow for bpetite.
#
# Prompts the user to choose what to stage — all changes, a selected
# subset, or whatever is already in the index — then shows the EXACT
# staged diff, asks for approval over that diff, writes the sentinel,
# and commits. This guarantees the approval event certifies the actual
# content of the resulting commit: no path can enter the commit after
# the human has approved the diff.
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

if [ -z "$(git status --porcelain)" ]; then
  echo ""
  echo "[ABORT] Working tree is clean; nothing to commit."
  exit 1
fi

echo ""
echo "=== Working Tree ==="
git status --short

echo ""
echo "Stage which changes?"
echo "  [a] all changes (git add -A)"
echo "  [s] select specific files"
echo "  [c] keep current index as-is"
read -r -p "Choice [a/s/c]: " STAGE_MODE

case "$STAGE_MODE" in
  a|A)
    git add -A
    ;;
  s|S)
    echo ""
    echo "Enter files to stage, space-separated. Paths are forwarded to"
    echo "'git add' verbatim, so directories and glob patterns work."
    read -r -p "Files: " -a STAGE_PATHS
    if [ ${#STAGE_PATHS[@]} -eq 0 ]; then
      echo "[ABORT] No files selected."
      exit 1
    fi
    git add -- "${STAGE_PATHS[@]}"
    ;;
  c|C)
    echo "[OK] Keeping current index."
    ;;
  *)
    echo "[ABORT] Unknown choice: '$STAGE_MODE'."
    exit 1
    ;;
esac

if git diff --cached --quiet; then
  echo ""
  echo "[ABORT] Nothing staged."
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
