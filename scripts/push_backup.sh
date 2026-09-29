#!/usr/bin/env bash
#
# Push the staged database to the backup branch with git.
#
# The contents API cannot reliably store a file this size against this
# repository: after three successful backups it began answering every upload
# with 403 {"message":"Timed out validating rule, please try again"}, and three
# retries over seven minutes did not shift it. GitHub's own error for an
# oversized upload says what to do instead — "Consider creating/updating the
# file in a local clone and pushing it to GitHub" — and a workflow runner has a
# clone and a credentialed remote already.
#
# The branch is cloned rather than force-created, so everything else living on
# it (the small learning backup, written by the app through the API) survives.
set -euo pipefail

: "${BACKUP_STAGE_PATH:?BACKUP_STAGE_PATH is not set — the job stages the database there}"
: "${GITHUB_REPOSITORY:?}"
: "${GH_PUSH_TOKEN:?a token with contents:write for this repository}"

BRANCH="${DB_BACKUP_BRANCH:-db-backup}"
DEST_PATH="${DB_BACKUP_FILE:-backups/market_data.sqlite3.gz}"

if [ ! -s "$BACKUP_STAGE_PATH" ]; then
  echo "::error title=Nothing to back up::$BACKUP_STAGE_PATH is missing or empty. The job did not stage a database, so there is nothing to push."
  exit 1
fi

remote="https://x-access-token:${GH_PUSH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# --depth 1: the history of this branch is a pile of multi-megabyte blobs and
# none of it is needed to add one more commit.
if git clone --quiet --depth 1 --branch "$BRANCH" "$remote" "$work" 2>/dev/null; then
  echo "Cloned existing branch '$BRANCH'."
else
  echo "Branch '$BRANCH' does not exist yet; creating it."
  git clone --quiet --depth 1 "$remote" "$work"
  git -C "$work" checkout --quiet -b "$BRANCH"
fi

git -C "$work" config user.name  "github-actions[bot]"
git -C "$work" config user.email "41898282+github-actions[bot]@users.noreply.github.com"

mkdir -p "$work/$(dirname "$DEST_PATH")"
cp "$BACKUP_STAGE_PATH" "$work/$DEST_PATH"

if git -C "$work" diff --quiet -- "$DEST_PATH" 2>/dev/null && \
   ! git -C "$work" status --porcelain -- "$DEST_PATH" | grep -q .; then
  echo "The stored backup is already identical; nothing to push."
  exit 0
fi

size_mb=$(awk "BEGIN{printf \"%.1f\", $(stat -c%s "$BACKUP_STAGE_PATH") / 1048576}")
# GitHub refuses any file over 100 MB. Fail with a message that says so before
# the push does, and warn while there is still room to act.
# The release copy (scripts/release_backup.py) has a 2 GB limit, so the data is
# still saved there; the run fails so the branch copy gets fixed.
if awk "BEGIN{exit !($size_mb >= 99)}"; then
  echo "::error title=Database backup too large for the branch::${size_mb} MB compressed; GitHub rejects files over 100 MB. Saved to the release copy only. Trim the backup (core.trim_backup_copy)."
  python3 "$(dirname "$0")/release_backup.py" || true
  exit 1
fi
if awk "BEGIN{exit !($size_mb >= 90)}"; then
  echo "::warning title=Database backup near GitHub's limit::${size_mb} MB compressed of 100 MB. Trim it soon (core.trim_backup_copy)."
fi
git -C "$work" add "$DEST_PATH"
git -C "$work" commit --quiet -m "Auto-backup DB $(date -u +%Y-%m-%dT%H:%M:%SZ) (${size_mb} MB compressed)"

# One retry: a push can lose a race with another job writing the same branch,
# and the concurrency group makes that rare rather than impossible.
if ! git -C "$work" push --quiet origin "$BRANCH"; then
  echo "Push rejected; refetching the branch and trying once more."
  git -C "$work" fetch --quiet --depth 1 origin "$BRANCH"
  git -C "$work" reset --quiet --hard FETCH_HEAD
  cp "$BACKUP_STAGE_PATH" "$work/$DEST_PATH"
  git -C "$work" add "$DEST_PATH"
  git -C "$work" commit --quiet -m "Auto-backup DB $(date -u +%Y-%m-%dT%H:%M:%SZ) (${size_mb} MB compressed)"
  git -C "$work" push origin "$BRANCH"
fi

echo "Pushed ${size_mb} MB to ${GITHUB_REPOSITORY}@${BRANCH}:${DEST_PATH}"

# Second copy, as a release asset. A failure here warns but does not fail the
# run: the branch copy above is saved.
python3 "$(dirname "$0")/release_backup.py" || \
  echo "::warning title=Release copy not updated::the branch backup above is saved; the release copy is one run behind."
