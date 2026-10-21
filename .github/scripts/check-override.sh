#!/usr/bin/env bash
# Succeeds (exit 0) only if the override label is CURRENTLY applied to the PR, and the most
# recent labeled/unlabeled event for it (with no unlabeled event after it) was applied by someone
# whose repository role is admin or maintain. Checking only the label's history (as opposed to its
# current state) would let a stripped label (see strip-override in claude-review.yml) still
# authorize a later run; checking only current presence would let an unauthorized re-application
# ride on an authorized actor's earlier event, so both are required.
#
# Pagination: `gh api --paginate --jq` applies the filter to each page separately, so a
# whole-history filter such as `last` would pick one event per page. Both queries therefore use
# `--paginate --slurp` (an array of pages) and flatten it with `add` before filtering.
# Env: GH_TOKEN, REPO (owner/name), PR (number), SHA (head commit, printed for audit on success),
#      LABEL (default override:ai-review)
set -euo pipefail
label="${LABEL:-override:ai-review}"
sha="${SHA:-unknown}"

current=$(gh api "repos/${REPO}/issues/${PR}/labels" --paginate --slurp |
  jq -r --arg label "${label}" '(add // []) | .[] | select(.name == $label) | .name')
if [ -z "${current}" ]; then
  echo "no current override (label '${label}' is not on the PR)"
  exit 1
fi

# The issue events API lists events oldest first. Keep only labeled/unlabeled events for this
# label and take the last one. If it isn't a "labeled" event, the label's last change was a
# removal (or there's no history at all), so there's no override to honor.
last_event=$(gh api "repos/${REPO}/issues/${PR}/events" --paginate --slurp |
  jq -c --arg label "${label}" \
    '[(add // [])[] | select((.event == "labeled" or .event == "unlabeled") and .label.name == $label)] | last')

event_type=$(jq -r '.event // empty' <<<"${last_event}")
actor=$(jq -r '.actor.login // empty' <<<"${last_event}")

if [ "${event_type}" != "labeled" ] || [ -z "${actor}" ]; then
  echo "no '${label}' label applied"
  exit 1
fi

# `.role_name` is the actual role (admin, maintain, write, triage, read or a custom role); the
# legacy `.permission` field reports maintain as "write" and would reject real maintainers.
role=$(gh api "repos/${REPO}/collaborators/${actor}/permission" --jq .role_name)
case "${role}" in
  admin | maintain)
    echo "override by ${actor} (${role}) accepted for ${sha}"
    exit 0
    ;;
  *)
    echo "override label applied by ${actor} (${role}) — not authorized"
    exit 1
    ;;
esac
