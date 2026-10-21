import re
from collections.abc import Sequence
from pathlib import Path

from sb_checks.doctor import DEFAULT_COMPOSE, PS_ARGS, Finding, diagnose


class FakeProbe:
    def __init__(
        self,
        tools: set[str],
        runs: dict[str, tuple[int, str]] | None = None,
        busy_ports: set[int] | None = None,
        files: set[str] | None = None,
    ) -> None:
        self.tools, self.runs = tools, runs or {}
        self.busy_ports, self.files = busy_ports or set(), files or set()

    def which(self, tool: str) -> str | None:
        return f"/bin/{tool}" if tool in self.tools else None

    def run(self, argv: Sequence[str]) -> tuple[int, str]:
        return self.runs.get(" ".join(argv), (0, ""))

    def port_free(self, port: int) -> bool:
        return port not in self.busy_ports

    def exists(self, path: str) -> bool:
        return path in self.files


ALL_TOOLS = {"uv", "docker", "mise", "gitleaks", "pyright-langserver"}
HOOKS = {".venv/bin/sb-agentkit"}


def by_name(findings: list[Finding]) -> dict[str, Finding]:
    return {f.name: f for f in findings}


def test_healthy_machine_is_all_ok() -> None:
    findings = diagnose(FakeProbe(ALL_TOOLS, files=HOOKS), env={})
    assert {f.status for f in findings} == {"ok"}


def test_missing_docker_is_a_failure_with_install_hint() -> None:
    finding = by_name(diagnose(FakeProbe(ALL_TOOLS - {"docker"}, files=HOOKS), env={}))["docker"]
    assert finding.status == "fail"
    assert "install" in finding.detail.lower()


def test_daemon_down_is_a_failure() -> None:
    probe = FakeProbe(ALL_TOOLS, runs={"docker info": (1, "Cannot connect")}, files=HOOKS)
    assert by_name(diagnose(probe, env={}))["docker daemon"].status == "fail"


def test_missing_optional_tools_are_warnings() -> None:
    findings = by_name(diagnose(FakeProbe({"uv", "docker"}), env={}))
    assert findings["mise"].status == "warn"
    assert findings["gitleaks"].status == "warn"
    assert findings["agent hooks"].status == "warn"
    assert "make bootstrap" in findings["agent hooks"].detail


def test_busy_port_not_owned_by_stack_warns_with_variable_name() -> None:
    probe = FakeProbe(ALL_TOOLS, busy_ports={5432}, files=HOOKS)
    finding = by_name(diagnose(probe, env={}))["port 5432"]
    assert finding.status == "warn"
    assert "SB_PG_PORT" in finding.detail


PS_KEY = " ".join([*DEFAULT_COMPOSE.split(), *PS_ARGS])


def test_busy_port_owned_by_our_postgres_is_ok() -> None:
    probe = FakeProbe(ALL_TOOLS, busy_ports={5432}, runs={PS_KEY: (0, "postgres\n")}, files=HOOKS)
    assert by_name(diagnose(probe, env={}))["port 5432"].status == "ok"


def test_temporal_ownership_covers_both_its_ports() -> None:
    probe = FakeProbe(
        ALL_TOOLS, busy_ports={7233, 8233}, runs={PS_KEY: (0, "temporal\n")}, files=HOOKS
    )
    found = by_name(diagnose(probe, env={}))
    assert found["port 7233"].status == "ok"
    assert found["port 8233"].status == "ok"


def test_custom_compose_command_is_used_for_ownership() -> None:
    key = "docker compose -f a.yml --env-file e " + " ".join(PS_ARGS)
    probe = FakeProbe(ALL_TOOLS, busy_ports={5432}, runs={key: (0, "postgres")}, files=HOOKS)
    findings = diagnose(probe, env={}, compose="docker compose -f a.yml --env-file e")
    assert by_name(findings)["port 5432"].status == "ok"


def test_failed_compose_query_is_reported_as_such() -> None:
    probe = FakeProbe(ALL_TOOLS, busy_ports={5432}, runs={PS_KEY: (1, "boom")}, files=HOOKS)
    detail = by_name(diagnose(probe, env={}))["port 5432"].detail
    assert "could not query the compose stack" in detail


def test_compose_v2_missing_is_a_failure() -> None:
    probe = FakeProbe(ALL_TOOLS, runs={"docker compose version": (1, "")}, files=HOOKS)
    assert by_name(diagnose(probe, env={}))["docker compose v2"].status == "fail"


def test_non_numeric_port_is_a_warning_not_a_crash() -> None:
    probe = FakeProbe(ALL_TOOLS, files=HOOKS)
    finding = by_name(diagnose(probe, env={"SB_PG_PORT": "abc"}))["SB_PG_PORT"]
    assert finding.status == "warn"


def test_port_override_from_env_is_checked() -> None:
    probe = FakeProbe(ALL_TOOLS, busy_ports={15432}, files=HOOKS)
    assert by_name(diagnose(probe, env={"SB_PG_PORT": "15432"}))["port 15432"].status == "warn"


REPO = Path(__file__).resolve().parents[3]


def test_short_admin_secret_in_the_process_env_is_a_warning() -> None:
    env = {"SB_ADMIN_SECRET_KEY": "x" * 31}
    finding = by_name(diagnose(FakeProbe(ALL_TOOLS, files=HOOKS), env=env))["admin secret"]
    assert finding.status == "warn"
    assert "32" in finding.detail
    assert "x" * 31 not in finding.detail  # never echo the secret


def test_long_enough_admin_secret_is_ok_and_unset_is_not_reported() -> None:
    env = {"SB_ADMIN_SECRET_KEY": "x" * 32}
    assert by_name(diagnose(FakeProbe(ALL_TOOLS, files=HOOKS), env=env))["admin secret"].status == (
        "ok"
    )
    assert "admin secret" not in by_name(diagnose(FakeProbe(ALL_TOOLS, files=HOOKS), env={}))


def test_env_example_admin_secret_is_long_enough_and_marked_dev_only() -> None:
    match = re.search(r"^SB_ADMIN_SECRET_KEY=(.*)$", (REPO / ".env.example").read_text(), re.M)
    assert match is not None
    value = match.group(1)
    assert len(value) >= 32
    assert "dev-only" in value
