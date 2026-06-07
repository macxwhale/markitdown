#!/usr/bin/env bash
# Safely sync this fork's main branch with upstream microsoft/markitdown
# *without* clobbering the api/ additions (or any other local changes).
#
# Why this exists: GitHub's "Sync fork" button (and `git reset --hard
# upstream/main`) performs a fast-forward/reset that throws away commits that
# only exist on the fork — which would delete api/, docker-compose.yml, etc.
# A merge, by contrast, is a three-way merge: files that only exist on one
# side (like api/) are simply kept, never dropped, and real conflicts are
# surfaced for you to resolve by hand instead of being silently resolved in
# upstream's favor.
#
# Usage:
#   api/sync-fork.sh                 # fetch + merge upstream/main into the
#                                     # current branch, then stop for review
#   api/sync-fork.sh --push          # ...and push the result to origin
#
# Safe to re-run. Aborts (with no changes made) if the working tree is dirty
# or if the merge produces conflicts, so you always end up in a clean,
# inspectable state.

set -euo pipefail

UPSTREAM_URL="https://github.com/microsoft/markitdown.git"
UPSTREAM_REMOTE="upstream"
UPSTREAM_BRANCH="main"
PUSH=false

for arg in "$@"; do
  case "$arg" in
    --push) PUSH=true ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--push]" >&2
      exit 1
      ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree is not clean. Commit or stash your changes first." >&2
  exit 1
fi

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "Adding '$UPSTREAM_REMOTE' remote -> $UPSTREAM_URL"
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Fetching $UPSTREAM_REMOTE/$UPSTREAM_BRANCH..."
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BRANCH"

echo "Merging $UPSTREAM_REMOTE/$UPSTREAM_BRANCH into $CURRENT_BRANCH (no fast-forward, no rebase)..."
if ! git merge --no-ff --no-edit \
    -m "Merge $UPSTREAM_REMOTE/$UPSTREAM_BRANCH into $CURRENT_BRANCH" \
    "$UPSTREAM_REMOTE/$UPSTREAM_BRANCH"; then
  echo >&2
  echo "error: merge produced conflicts. Resolve them, 'git add' the files, and" >&2
  echo "       'git commit' to finish — or 'git merge --abort' to back out." >&2
  echo "       (api/ should never conflict; conflicts mean upstream touched a" >&2
  echo "       path you've also modified — review carefully before resolving.)" >&2
  exit 1
fi

echo "Merge complete. 'git log --oneline -5' and 'git status' to review."

if [ "$PUSH" = true ]; then
  echo "Pushing $CURRENT_BRANCH to origin..."
  git push origin "$CURRENT_BRANCH"
fi
