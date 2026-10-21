from pathlib import Path, PurePosixPath

import pytest

from sb_checks.allowlist import AllowEntry, AllowlistError, apply_allowlist, load_allowlist
from sb_checks.core import Violation


def test_missing_allowlist_file_means_no_entries(tmp_path: Path) -> None:
    assert load_allowlist(tmp_path / "absent.toml") == ()


def test_loads_entries_with_reasons(tmp_path: Path) -> None:
    file = tmp_path / "allowlist.toml"
    file.write_text(
        '[[allow]]\ncheck = "no-float"\npath = "a/b.py"\n'
        'reason = "vendored numeric kernel; tracked in ADR-0015"\n'
    )
    assert load_allowlist(file) == (
        AllowEntry(
            "no-float", PurePosixPath("a/b.py"), "vendored numeric kernel; tracked in ADR-0015"
        ),
    )


def test_entry_without_real_reason_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "allowlist.toml"
    file.write_text('[[allow]]\ncheck = "no-float"\npath = "a/b.py"\nreason = "ok"\n')
    with pytest.raises(AllowlistError, match="reason"):
        load_allowlist(file)


def test_malformed_toml_raises_allowlist_error_naming_the_file(tmp_path: Path) -> None:
    file = tmp_path / "allowlist.toml"
    file.write_text("[[allow]\ncheck = ")
    with pytest.raises(AllowlistError, match=r"allowlist\.toml"):
        load_allowlist(file)


def test_allowlisted_violation_is_dropped() -> None:
    violation = Violation(PurePosixPath("a/b.py"), 3, "no-float", "m")
    entry = AllowEntry("no-float", PurePosixPath("a/b.py"), "a sufficiently long reason")
    assert apply_allowlist([violation], [entry]) == []


def test_entry_that_excuses_nothing_becomes_a_stale_violation() -> None:
    entry = AllowEntry("no-float", PurePosixPath("gone.py"), "a sufficiently long reason")
    [stale] = apply_allowlist([], [entry])
    assert stale.check_id == "stale-allowlist"
    assert "gone.py" in stale.message


def test_duplicate_entry_is_reported_as_duplicate_not_stale() -> None:
    violation = Violation(PurePosixPath("a/b.py"), 3, "no-float", "m")
    entry = AllowEntry("no-float", PurePosixPath("a/b.py"), "a sufficiently long reason")
    twin = AllowEntry("no-float", PurePosixPath("a/b.py"), "a different but long reason")
    [duplicate] = apply_allowlist([violation], [entry, twin])
    assert duplicate.check_id == "stale-allowlist"
    assert duplicate.message == "duplicate allowlist entry for a/b.py [no-float]; delete it"
