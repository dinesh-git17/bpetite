#!/bin/bash
#
# Bootstrap the bpetite pre-commit hook system.
#
# Installs the pre-commit and pre-push git hooks declared in
# .pre-commit-config.yaml and ensures scripts/commitall.sh is executable.
# Run once per clone, after `pre-commit` is available on PATH (e.g. via
# `uv tool install pre-commit`, `pipx install pre-commit`, or `brew install
# pre-commit`).
#
# Usage: bash setup-hooks.sh
#
set -e

echo "Installing pre-commit hooks..."
pre-commit install

chmod +x scripts/commitall.sh

echo ""
echo "[OK] Hooks installed. Direct commits are now blocked."
echo "     Use 'bash scripts/commitall.sh' or /commitall to commit."
