"""Drive the real Makefile with a fake compose command: no containers are started."""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def make(*args: str, services: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    extra = [f"SERVICES={' '.join(services)}"] if services else ["SERVICES="]
    return subprocess.run(
        # COMPOSE first: a later COMPOSE=... in `args` overrides it (the last assignment wins).
        ["make", "--no-print-directory", "COMPOSE=echo compose", *args, *extra],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_bare_up_prints_usage_and_starts_nothing() -> None:
    result = make("up")
    assert result.returncode == 0
    assert "usage: make up infra | make up <service...>" in result.stdout
    assert "compose" not in result.stdout.replace("docker compose", "")


def test_up_infra_starts_core_profile_with_wait() -> None:
    result = make("up", "infra")
    assert result.returncode == 0
    assert "compose --profile core up -d --wait" in result.stdout
    assert "compose --profile init run --rm kafka-init" in result.stdout


def test_unknown_name_fails_and_lists_valid_names() -> None:
    result = make("up", "ledgr", services=("ledger",))
    assert result.returncode != 0
    assert "unknown service 'ledgr'" in result.stdout + result.stderr
    assert "infra ledger" in result.stdout + result.stderr
    assert "--profile core" not in result.stdout


def test_service_brings_infra_up_first_then_migrates_then_starts() -> None:
    lines = make("up", "ledger", services=("ledger",)).stdout.splitlines()
    core = next(i for i, line in enumerate(lines) if "--profile core up -d --wait" in line)
    migrate = next(
        i
        for i, line in enumerate(lines)
        if "--profile core --profile ledger-migrate run --rm --build ledger-migrate" in line
    )
    start = next(
        i
        for i, line in enumerate(lines)
        if "--profile core --profile ledger up -d --build --wait" in line
    )
    assert core < migrate < start


def test_seed_execs_the_service_seed_module_in_its_api_container() -> None:
    """Service containers depend_on infra services, so every service-profile invocation also
    loads the core profile (compose rejects a depends_on target outside the active profiles)."""
    result = make("seed", "SVC=ledger")
    assert result.returncode == 0
    assert "compose --profile core --profile ledger exec " in result.stdout
    assert "ledger-api python -m ledger.seed" in result.stdout


def test_seed_without_svc_prints_usage() -> None:
    result = make("seed")
    assert result.returncode != 0
    assert "usage: make seed SVC=<service>" in result.stdout + result.stderr


@pytest.mark.parametrize("target", ["db-migrate", "db-downgrade"])
def test_db_targets_load_the_core_profile(target: str) -> None:
    result = make(target, "SVC=ledger")
    assert result.returncode == 0
    assert "compose --profile core --profile ledger-migrate run --rm ledger-migrate" in (
        result.stdout
    )


@pytest.mark.parametrize("target", ["down", "ps"])
def test_lifecycle_targets_use_all_profiles(target: str) -> None:
    assert "--profile '*'" in make(target).stdout


def test_reset_requires_confirmation_non_interactively() -> None:
    result = subprocess.run(
        ["make", "--no-print-directory", "reset", "COMPOSE=echo compose"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode != 0
    assert "CONFIRM=1" in result.stdout + result.stderr
    assert "down -v" not in result.stdout
    assert "down -v" in make("reset", "CONFIRM=1").stdout


def fake_compose(tmp_path: Path, *services: str) -> str:
    """A compose stand-in: `config --services` lists `services`; anything else is echoed."""
    script = tmp_path / "compose"
    listing = "\n".join(services)
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in *"config --services"*) printf \'%s\\n\' "' + listing + '" ;; '
        '*) echo compose "$@" ;; esac\n'
    )
    script.chmod(0o755)
    return str(script)


def test_restart_restarts_the_service_processes(tmp_path: Path) -> None:
    """The worker and consumer have no reloader: `make restart <svc>` picks up edits."""
    compose = fake_compose(tmp_path, "ledger-api", "ledger-worker", "ledger-consumer")
    result = make("restart", "ledger", f"COMPOSE={compose}", services=("ledger",))
    assert result.returncode == 0
    assert (
        "compose --profile core --profile ledger restart ledger-api ledger-worker ledger-consumer"
        in result.stdout
    )


def test_restart_rejects_unknown_names() -> None:
    result = make("restart", "ledgr", services=("ledger",))
    assert result.returncode != 0
    assert "unknown service 'ledgr'" in result.stdout + result.stderr


@pytest.mark.parametrize("target", ["logs", "restart"])
def test_logs_and_restart_name_only_the_services_compose_defines(
    tmp_path: Path, target: str
) -> None:
    """A generated service has an API but no worker or consumer until those seams exist; naming a
    service compose does not define fails the whole command."""
    compose = fake_compose(tmp_path, "postgres", "demo_svc-migrate", "demo_svc-api")
    result = make(target, "demo_svc", f"COMPOSE={compose}", services=("demo_svc",))
    assert result.returncode == 0, result.stdout + result.stderr
    [line] = [  # what the fake compose received (make also echoes the recipe line)
        line
        for line in result.stdout.splitlines()
        if line.startswith("compose ") and f" {target} " in line
    ]
    assert line.endswith(" demo_svc-api")
    assert "demo_svc-worker" not in line
    assert "demo_svc-consumer" not in line


def test_restart_with_no_defined_process_exits_two_and_restarts_nothing(tmp_path: Path) -> None:
    """With an empty process list, `compose restart` would restart every service in the
    profiles (infra included); the target refuses instead."""
    compose = fake_compose(tmp_path, "postgres", "demo_svc-migrate")
    result = make("restart", "demo_svc", f"COMPOSE={compose}", services=("demo_svc",))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "no processes to restart for demo_svc" in result.stdout + result.stderr
    assert not [line for line in result.stdout.splitlines() if line.startswith("compose ")]


@pytest.mark.parametrize(
    "args",
    [
        ("seed",),
        ("db-migrate",),
        ("db-downgrade",),
        ("db-revision", "M=x"),
    ],
)
def test_svc_and_message_reach_the_shell_as_data(tmp_path: Path, args: tuple[str, ...]) -> None:
    """SVC and M pass through the environment ("$SVC"), never expanded into the recipe text, so
    shell syntax in them is never run."""
    marker = tmp_path / "ran"
    target, *rest = args
    result = make(target, f"SVC=x`touch {marker}`", *rest, "UV=echo uv", services=("ledger",))
    assert not marker.exists(), result.stdout + result.stderr
    if target == "db-revision":
        message = make(target, "SVC=ledger", f"M=x`touch {marker}`", "UV=echo uv")
        assert not marker.exists(), message.stdout + message.stderr


def test_seed_runs_without_the_admin_credentials() -> None:
    """The seed runs inside the API container (`exec`), so it blanks the admin credentials it
    would otherwise inherit from the API's environment."""
    result = make("seed", "SVC=ledger")
    assert result.returncode == 0
    [line] = [line for line in result.stdout.splitlines() if line.startswith("compose ")]
    for name in ("LEDGER_ADMIN_USERNAME", "LEDGER_ADMIN_PASSWORD", "LEDGER_ADMIN_SECRET_KEY"):
        assert f"-e {name}= " in line
    assert line.endswith("ledger-api python -m ledger.seed")
