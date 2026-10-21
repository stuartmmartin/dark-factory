"""Exercises .github/scripts/check-override.sh against a fake `gh` CLI on PATH.

The fake `gh` serves canned JSON fixtures through the real `jq` binary, so the script's actual
`--jq` filters run exactly as they would against the GitHub API.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check-override.sh"
LABEL = "override:ai-review"

# Emulates `gh api` pagination: fixtures are lists of PAGES. `--paginate` without `--slurp`
# applies `--jq` to each page separately (as real gh does, so a whole-list filter like `last`
# is wrong across pages); `--paginate --slurp` prints one JSON array of all pages and, like
# real gh, refuses `--jq`.
FAKE_GH = r"""#!/usr/bin/env bash
set -euo pipefail
if [ "$1" != "api" ]; then
  echo "fake gh: unsupported command: $*" >&2
  exit 1
fi
path="$2"
shift 2
jq_filter="."
paginate=0
slurp=0
while [ $# -gt 0 ]; do
  case "$1" in
    --jq) jq_filter="$2"; shift 2 ;;
    --paginate) paginate=1; shift ;;
    --slurp) slurp=1; shift ;;
    *) shift ;;
  esac
done
case "$path" in
  */issues/*/labels) pages="$FIXTURES_DIR/labels.json" ;;
  */issues/*/events) pages="$FIXTURES_DIR/events.json" ;;
  */collaborators/*/permission)
    actor=$(echo "$path" | sed -E 's#.*/collaborators/([^/]+)/permission#\1#')
    jq -r "$jq_filter" "$FIXTURES_DIR/permission-${actor}.json"
    exit 0
    ;;
  *)
    echo "fake gh: unknown path: $path" >&2
    exit 1
    ;;
esac
if [ "$slurp" = 1 ]; then
  if [ "$paginate" != 1 ] || [ "$jq_filter" != "." ]; then
    echo "fake gh: --slurp needs --paginate and cannot be combined with --jq" >&2
    exit 1
  fi
  jq -c . "$pages"
elif [ "$paginate" = 1 ]; then
  jq -c '.[]' "$pages" | while IFS= read -r page; do echo "$page" | jq -r "$jq_filter"; done
else
  jq -c '.[0]' "$pages" | jq -r "$jq_filter"
fi
"""


def _write_fake_gh(bin_dir: Path) -> None:
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)


def _event(event: str, actor: str, label: str = LABEL) -> dict[str, object]:
    return {"event": event, "label": {"name": label}, "actor": {"login": actor}}


# The legacy `.permission` field reports maintain as "write" and triage as "read";
# `.role_name` is the real role.
LEGACY_PERMISSION = {"admin": "admin", "maintain": "write", "write": "write", "triage": "read"}


def _pages(items: list[object]) -> list[list[object]]:
    """Split a flat list into two API pages (the second may be empty)."""
    half = (len(items) + 1) // 2
    return [items[:half], items[half:]]


def _run(
    tmp_path: Path,
    labels: list[str],
    events: list[dict[str, object]] | list[list[dict[str, object]]],
    permissions: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_gh(bin_dir)
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    label_items: list[object] = [{"name": n} for n in labels]
    (fixtures_dir / "labels.json").write_text(json.dumps(_pages(label_items)))
    paged = events and isinstance(events[0], list)
    event_pages = events if paged else _pages(list(events))
    (fixtures_dir / "events.json").write_text(json.dumps(event_pages))
    for actor, role in permissions.items():
        (fixtures_dir / f"permission-{actor}.json").write_text(
            json.dumps({"permission": LEGACY_PERMISSION.get(role, role), "role_name": role})
        )
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FIXTURES_DIR"] = str(fixtures_dir)
    env["GH_TOKEN"] = "test-token"  # noqa: S105 - fake gh ignores it; not a real credential
    env["REPO"] = "acme/widgets"
    env["PR"] = "42"
    env["SHA"] = "deadbeef"
    return subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env, check=False)


def test_label_not_currently_present_exits_1(tmp_path: Path) -> None:
    result = _run(tmp_path, labels=[], events=[_event("labeled", "admin-user")], permissions={})
    assert result.returncode == 1
    assert "no current override" in result.stdout


def test_labeled_then_unlabeled_then_labeled_by_admin_exits_0(tmp_path: Path) -> None:
    events = [
        _event("labeled", "alice"),
        _event("unlabeled", "alice"),
        _event("labeled", "admin-user"),
    ]
    result = _run(tmp_path, labels=[LABEL], events=events, permissions={"admin-user": "admin"})
    assert result.returncode == 0
    assert "admin-user" in result.stdout
    assert "deadbeef" in result.stdout


def test_labeled_by_admin_then_unlabeled_exits_1(tmp_path: Path) -> None:
    events = [_event("labeled", "admin-user"), _event("unlabeled", "admin-user")]
    result = _run(tmp_path, labels=[], events=events, permissions={"admin-user": "admin"})
    assert result.returncode == 1
    assert "no current override" in result.stdout


def test_labeled_by_write_only_user_exits_1(tmp_path: Path) -> None:
    events = [_event("labeled", "writer-user")]
    result = _run(tmp_path, labels=[LABEL], events=events, permissions={"writer-user": "write"})
    assert result.returncode == 1
    assert "not authorized" in result.stdout


def test_latest_event_on_a_later_page_wins(tmp_path: Path) -> None:
    """A writer's label on page 1, then an admin's removal and re-application on page 2."""
    events = [
        [_event("labeled", "writer-user")],
        [_event("unlabeled", "admin-user"), _event("labeled", "admin-user")],
    ]
    permissions = {"writer-user": "write", "admin-user": "admin"}
    result = _run(tmp_path, labels=[LABEL], events=events, permissions=permissions)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "override by admin-user" in result.stdout


def test_unauthorized_reapplication_on_a_later_page_is_rejected(tmp_path: Path) -> None:
    events = [
        [_event("labeled", "admin-user")],
        [_event("unlabeled", "writer-user"), _event("labeled", "writer-user")],
    ]
    permissions = {"writer-user": "write", "admin-user": "admin"}
    result = _run(tmp_path, labels=[LABEL], events=events, permissions=permissions)
    assert result.returncode == 1
    assert "writer-user" in result.stdout
    assert "not authorized" in result.stdout


def test_label_present_only_on_second_labels_page_counts(tmp_path: Path) -> None:
    labels = ["bug", "needs-triage", LABEL]
    events = [_event("labeled", "admin-user")]
    result = _run(tmp_path, labels=labels, events=events, permissions={"admin-user": "admin"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_maintain_role_is_accepted_via_role_name(tmp_path: Path) -> None:
    """The legacy `.permission` field says "write" for maintainers; `.role_name` is right."""
    events = [_event("labeled", "maint-user")]
    result = _run(tmp_path, labels=[LABEL], events=events, permissions={"maint-user": "maintain"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "maintain" in result.stdout


def test_triage_role_is_rejected(tmp_path: Path) -> None:
    events = [_event("labeled", "triager")]
    result = _run(tmp_path, labels=[LABEL], events=events, permissions={"triager": "triage"})
    assert result.returncode == 1
    assert "not authorized" in result.stdout
