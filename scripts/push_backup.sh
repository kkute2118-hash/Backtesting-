#!/usr/bin/env bash
#
# Publish the staged database as a GitHub Release asset.
#
# It used to be a git push to the db-backup branch. That stopped working the
# moment the universe grew: a full NSE build compresses to 116 MB and GitHub
# hard-rejects any file over 100 MB on push, so a 37-minute download finished
# and then saved nothing. Release assets take up to 2 GB, and - just as
# usefully - replacing one does not add another multi-megabyte blob to a
# branch's history, which the old scheme did on every single sync.
#
# The branch is left exactly as it is. The app still falls back to reading
# backups/market_data.sqlite3.gz from it, so an older instance that has not
# picked up the new restore path keeps working off the last committed copy
# until this script's asset supersedes it.
#
# No secret is ever echoed: the token goes in an Authorization header built
# inline, and curl is given --fail-with-body so a rejection surfaces the
# server's message rather than the request.
set -euo pipefail

: "${BACKUP_STAGE_PATH:?BACKUP_STAGE_PATH is not set - the job stages the database there}"
: "${GITHUB_REPOSITORY:?}"
: "${GH_PUSH_TOKEN:?a token with contents:write for this repository}"

TAG="${DB_BACKUP_RELEASE_TAG:-db-backup-latest}"
ASSET="${DB_BACKUP_ASSET:-market_data.sqlite3.gz}"
API="https://api.github.com/repos/${GITHUB_REPOSITORY}"
UPLOADS="https://uploads.github.com/repos/${GITHUB_REPOSITORY}"

if [ ! -s "$BACKUP_STAGE_PATH" ]; then
  echo "::error title=Nothing to back up::$BACKUP_STAGE_PATH is missing or empty. The job did not stage a database, so there is nothing to push."
  exit 1
fi

size_mb=$(awk "BEGIN{printf \"%.1f\", $(stat -c%s "$BACKUP_STAGE_PATH") / 1048576}")

gh_api() {
  curl --silent --show-error --fail-with-body \
       -H "Authorization: token ${GH_PUSH_TOKEN}" \
       -H "Accept: application/vnd.github+json" \
       -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

# The release is a container, not an announcement: it is marked as a
# prerelease so it never shows up as the repository's latest release, and the
# body says what it is so nobody deletes it wondering.
release_json="$(gh_api "${API}/releases/tags/${TAG}" 2>/dev/null || true)"
release_id="$(printf '%s' "$release_json" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9]\+\).*/\1/p' | head -1)"

if [ -z "$release_id" ]; then
  echo "Release '${TAG}' does not exist yet; creating it."
  created="$(gh_api -X POST "${API}/releases" -d "$(cat <<JSON
{"tag_name":"${TAG}","name":"Database backup","prerelease":true,
 "body":"Automated candle-store backup. The asset on this release is the live database; it is replaced in place by the sync and history-build workflows. Deleting it loses every stored candle and forward test."}
JSON
)")"
  release_id="$(printf '%s' "$created" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9]\+\).*/\1/p' | head -1)"
fi

if [ -z "$release_id" ]; then
  echo "::error title=Could not resolve the backup release::Creating or reading release '${TAG}' did not return an id."
  exit 1
fi

# An asset name is unique per release, so the old one has to go before the new
# one can take its name. Deleting first means a failed upload leaves the
# release with no asset at all - which is loud, and better than silently
# keeping a stale database that looks current.
assets="$(gh_api "${API}/releases/${release_id}/assets")"
old_id="$(printf '%s' "$assets" \
  | tr '}' '\n' \
  | grep -F "\"name\":\"${ASSET}\"" \
  | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9]\+\).*/\1/p' | head -1)"

if [ -n "$old_id" ]; then
  echo "Replacing the existing '${ASSET}' asset."
  gh_api -X DELETE "${API}/releases/assets/${old_id}" >/dev/null
fi

echo "Uploading ${size_mb} MB as '${ASSET}'..."
curl --silent --show-error --fail-with-body \
     -H "Authorization: token ${GH_PUSH_TOKEN}" \
     -H "Accept: application/vnd.github+json" \
     -H "Content-Type: application/gzip" \
     --data-binary @"${BACKUP_STAGE_PATH}" \
     "${UPLOADS}/releases/${release_id}/assets?name=${ASSET}" >/dev/null

# Read it back. An upload that returns 201 and stores nothing usable is the
# failure this whole script exists to prevent, and the run is worthless
# without a saved database - so confirm the asset is there and the right size
# before reporting success.
check="$(gh_api "${API}/releases/${release_id}/assets")"
stored="$(printf '%s' "$check" | tr '}' '\n' | grep -F "\"name\":\"${ASSET}\"" \
  | sed -n 's/.*"size"[[:space:]]*:[[:space:]]*\([0-9]\+\).*/\1/p' | head -1)"
actual="$(stat -c%s "$BACKUP_STAGE_PATH")"

if [ "$stored" != "$actual" ]; then
  echo "::error title=Backup did not store correctly::Uploaded ${actual} bytes but the release reports '${stored:-none}'. The database is NOT saved."
  exit 1
fi

echo "Stored ${size_mb} MB at ${GITHUB_REPOSITORY} release ${TAG} -> ${ASSET}"
