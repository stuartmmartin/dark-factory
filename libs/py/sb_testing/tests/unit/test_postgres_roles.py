"""The test container's roles are the compose roles (compose/postgres/init/01-roles.sh)."""

import re
from pathlib import Path

from sb_testing.postgres import ROLE_SQL_TEMPLATE

REPO = Path(__file__).resolve().parents[5]
_CREATE_ROLE = re.compile(r"CREATE ROLE .*?;")


def _normalised(statements: list[str]) -> list[str]:
    """Blank out the password literal, which differs (env var vs test constant)."""
    return [re.sub(r"PASSWORD '[^']*'", "PASSWORD '?'", s) for s in statements]


def test_container_roles_match_the_compose_init_script() -> None:
    script = (REPO / "compose/postgres/init/01-roles.sh").read_text()
    compose_roles = _normalised(_CREATE_ROLE.findall(script))
    test_roles = _normalised(_CREATE_ROLE.findall(ROLE_SQL_TEMPLATE))
    assert len(compose_roles) == 3
    assert test_roles == compose_roles


def test_container_grants_nothing_broad_on_the_public_schema() -> None:
    assert "GRANT ALL" not in ROLE_SQL_TEMPLATE.upper()
