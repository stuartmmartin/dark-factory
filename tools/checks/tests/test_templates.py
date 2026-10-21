"""The Copier service and use-case templates: a generated service passes the machines first try.

Every render goes into `tmp_path`, never into `services/`. The machine checks run the repo's own
tools and configs against the rendered tree (ruff/pyright configs are copied next to it, so
their relative globs apply to it), and the import contracts come from the rendered
`REGISTER.md`, so the snippets a human pastes are what gets verified.

The make-target tests run the real Makefile with `UV=false`: a guard that failed to refuse would
reach `false run copier ...` and fail without writing anything.
"""

import ast
import configparser
import json
import keyword
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from copier import run_copy

REPO = Path(__file__).resolve().parents[3]
SERVICE_TEMPLATE = REPO / "tools" / "templates" / "service"
USE_CASE_TEMPLATE = REPO / "tools" / "templates" / "use_case"
BIN = Path(sys.executable).parent  # the workspace venv's tools (ruff, pyright, lint-imports, ...)
NAME = "demo_svc"
OTHER = "long_service_name_for_ci"  # the longest service name allowed (24)
LONG_USE_CASE = "reconcile_the_quarterly_accounts"  # the longest use case name allowed (32)
TIMEOUT = 600

SERVICE_FILES = [
    "pyproject.toml",
    "alembic.ini",
    "Dockerfile",
    "CLAUDE.md",
    "CONTEXT.md",
    "REGISTER.md",
    "src/{n}/__init__.py",
    "src/{n}/py.typed",
    "src/{n}/bootstrap.py",
    "src/{n}/main.py",
    "src/{n}/migrate.py",
    "src/{n}/domain/__init__.py",
    "src/{n}/domain/amounts.py",
    "src/{n}/application/__init__.py",
    "src/{n}/application/ports.py",
    "src/{n}/application/dto.py",
    "src/{n}/application/policies/__init__.py",
    "src/{n}/application/use_cases/__init__.py",
    "src/{n}/application/use_cases/ping.py",
    "src/{n}/infrastructure/__init__.py",
    "src/{n}/infrastructure/settings.py",
    "src/{n}/infrastructure/models.py",
    "src/{n}/infrastructure/repositories.py",
    "src/{n}/infrastructure/uow.py",
    "src/{n}/interface/__init__.py",
    "src/{n}/interface/http/__init__.py",
    "src/{n}/interface/http/schemas.py",
    "src/{n}/interface/http/routes.py",
    "src/{n}/interface/admin/__init__.py",
    "src/{n}/interface/admin/views.py",
    "src/{n}/interface/admin/acceptors.py",
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/versions/0001_initial.py",
    "tests/conftest.py",
    "tests/{n}_fakes.py",
    "tests/unit/conftest.py",
    "tests/unit/test_settings.py",
    "tests/unit/test_fakes.py",
    "tests/unit/test_bootstrap.py",
    "tests/unit/test_main.py",
    "tests/unit/test_migrate.py",
    "tests/unit/use_cases/test_ping.py",
    "tests/integration/db/test_migrations.py",
    "tests/integration/http/conftest.py",
    "tests/integration/http/test_routes.py",
]


def render_service(root: Path, name: str = NAME, **data: object) -> Path:
    dst = root / "services" / name
    run_copy(str(SERVICE_TEMPLATE), dst, data={"name": name, **data}, defaults=True, quiet=True)
    return dst


def render_use_case(service: Path, name: str) -> None:
    run_copy(
        str(USE_CASE_TEMPLATE),
        service,
        data={"svc": service.name, "name": name},
        defaults=True,
        quiet=True,
    )


def fenced_blocks(markdown: str, heading: str) -> list[str]:
    """The fenced code blocks of the `### <heading>` section of REGISTER.md."""
    section = markdown.split(f"### {heading}", 1)[1].split("\n### ", 1)[0]
    return re.findall(r"```[a-z]*\n(.*?)```", section, flags=re.DOTALL)


def run(
    *argv: str | Path, env: dict[str, str] | None = None, cwd: Path = REPO
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(a) for a in argv],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
    )


def assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"{result.args}\n{result.stdout}\n{result.stderr}"


def env_for(root: Path, *names: str) -> dict[str, str]:
    # Only src: each service's tests/conftest.py must put its own tests/ (the fakes) on sys.path.
    paths = [str(root / "services" / n / "src") for n in names]
    # What `uv sync` would add: the distribution metadata (bootstrap reads its own version).
    site = root / "site"
    for name in names:
        info = site / f"{name}-0.1.0.dist-info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.1.0\n")
    return {**os.environ, "PYTHONPATH": os.pathsep.join([*paths, str(site)])}


def ruff(root: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    """ruff with the repo's ruff.toml, run from `root`: with `--config`, ruff resolves the
    config's relative globs (per-file-ignores, `src`) against the cwd, so they apply to the
    rendered tree. `src` also lists the repo's libraries, so `sb_*` stay first-party."""
    src = ["services/*/src", *(str(REPO / p) for p in ("tools/*/src", "libs/py/*/src"))]
    config = ("--config", REPO / "ruff.toml", "--config", f"src = {json.dumps(src)}")
    return run(BIN / "ruff", *args[:1], *config, *args[1:], cwd=root)


def pyright_config(root: Path, *names: str) -> Path:
    """The repo's pyrightconfig.json (same strict globs) with the workspace venv."""
    config = json.loads((REPO / "pyrightconfig.json").read_text())
    config.update(
        venvPath=str(REPO),
        include=["services"],
        extraPaths=[f"services/{n}/src" for n in names],
    )
    path = root / "pyrightconfig.json"
    path.write_text(json.dumps(config))
    return path


def importlinter_config(root: Path, *names: str) -> Path:
    libs = sorted(p.name for p in (REPO / "libs" / "py").iterdir() if (p / "src").is_dir())
    contracts = [
        block
        for n in names
        for heading in (".importlinter", "Services never import services")
        for block in fenced_blocks((root / "services" / n / "REGISTER.md").read_text(), heading)
        if "[importlinter:contract:" in block
    ]
    header = "[importlinter]\ninclude_external_packages = True\nroot_packages =\n"
    header += "".join(f"    {p}\n" for p in (*libs, *names))
    path = root / "importlinter.ini"
    path.write_text(header + "\n" + "\n".join([*contracts, *shared_contracts(names)]))
    return path


def shared_contracts(names: tuple[str, ...]) -> list[str]:
    """The repo's shared contracts that REGISTER.md says to extend, with the rendered services as
    their service side (as a human's paste would make them)."""
    repo = configparser.ConfigParser()
    repo.read(REPO / ".importlinter")
    blocks = []
    for contract, key in (
        ("libs-never-import-services", "forbidden_modules"),
        ("testing-only-in-tests", "source_modules"),
    ):
        section = dict(repo[f"importlinter:contract:{contract}"])
        section[key] = "\n".join(names)  # only the rendered services
        lines = [f"[importlinter:contract:{contract}]"]
        for option, value in section.items():
            values = value.split()
            if option == "name":
                lines.append(f"name = {value}")
            elif len(values) == 1 and option == "type":
                lines.append(f"type = {value}")
            else:
                lines += [f"{option} =", *(f"    {v}" for v in values)]
        blocks.append("\n".join(lines) + "\n")
    return blocks


def lint_imports(root: Path, config: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # From `root` and without a cache, so the repo's .import_linter_cache is never touched.
    return run(BIN / "lint-imports", "--no-cache", "--config", config, env=env, cwd=root)


def pytest_in(
    root: Path, *args: str | Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """pytest with the repo's config (importlib mode, asyncio auto) and `root` as rootdir, so
    node ids read `services/<name>/tests/...`; no cache is written."""
    config = ("-c", REPO / "pyproject.toml", "--rootdir", root, "-p", "no:cacheprovider")
    return run(BIN / "pytest", *config, *args, env=env)


def make(*args: str) -> subprocess.CompletedProcess[str]:
    # UV=false: a guard that failed to refuse reaches `false run copier` and writes nothing.
    return run(
        "make", "--no-print-directory", *args, "UV=false", f"SCAFFOLD_PYTHON={sys.executable}"
    )


def test_service_renders_the_ledger_layout(tmp_path: Path) -> None:
    service = render_service(tmp_path)

    missing = [f for f in (p.format(n=NAME) for p in SERVICE_FILES) if not (service / f).is_file()]
    assert missing == []
    files = [p for p in service.rglob("*") if p.is_file()]
    leaked = [p for p in files if "ledger" in (str(p) + p.read_text()).lower()]
    assert leaked == []
    for file in (p for p in files if p.suffix == ".py"):
        ast.parse(file.read_text(), filename=str(file))

    register = (service / "REGISTER.md").read_text()
    assert f'path = "{NAME}"' in register  # tach module
    assert f'"services/{NAME}/src"' in register  # tach source root
    for contract in (f"{NAME}-layers", f"{NAME}-pure-core"):
        assert f"[importlinter:contract:{contract}]" in register
    assert f"add `{NAME}` to `forbidden_modules` of `libs-never-import-services`" in register
    assert "libs-never-import-demo_svc" not in register
    assert "demo-svc" in register  # k8s names: the hyphenated form
    assert "`deploy/k8s/demo-svc/`" in register  # the k8s dir deploy.yml and images.yml use
    assert "deploy/k8s/demo_svc" not in register
    # Registration instructions describe both root coverage and complete contract enforcement.
    for registration in (
        "tach `source_roots`",
        "import-linter `root_packages`",
        "pyright `include`",
        "pytest `testpaths`",
    ):
        assert registration in register
    assert "names each missing registration" not in register
    assert "A1/A2/A9 go unenforced" not in register
    assert "Partial\ncontracts and import exemptions fail" in register
    assert "OpenAPI service discovery is automatic" in register
    assert "NEXT_API_PORT" in register  # the port-collision note
    assert f"  {NAME}-api:" in register  # compose stanza
    assert f"  {NAME}-migrate:" in register
    # A second service in the workspace: uv --locked needs every member manifest.
    dockerfile = (service / "Dockerfile").read_text()
    assert "services/*/pyproject.toml" in dockerfile
    assert "--package ${SERVICE}" in dockerfile


def test_the_compose_stanza_uses_the_given_port(tmp_path: Path) -> None:
    service = tmp_path / "services" / NAME
    run_copy(str(SERVICE_TEMPLATE), service, data={"name": NAME, "api_port": 8007}, defaults=True)
    assert "127.0.0.1:${SB_DEMO_SVC_API_PORT:-8007}:8000" in (service / "REGISTER.md").read_text()


@pytest.mark.integration
def test_generated_service_passes_the_machines(tmp_path: Path) -> None:
    """Two services in one tree: their unit suites run in ONE pytest session (no `fakes`
    module collision), then ruff, pyright, import-linter (REGISTER.md snippets) and sb-checks."""
    services = [render_service(tmp_path, NAME), render_service(tmp_path, OTHER, peers=NAME)]
    env = env_for(tmp_path, NAME, OTHER)

    tests = pytest_in(tmp_path, "-v", *(s / "tests" / "unit" for s in services), env=env)
    assert_ok(tests)
    for name in (NAME, OTHER):
        assert re.search(
            rf"services/{name}/tests/unit/use_cases/test_ping.py::test_R1_\S+ PASSED", tests.stdout
        ), tests.stdout

    assert_ok(ruff(tmp_path, "check", "services"))
    assert_ok(ruff(tmp_path, "format", "--check", "services"))
    assert_ok(run(BIN / "pyright", "-p", pyright_config(tmp_path, NAME, OTHER), env=env))
    config = importlinter_config(tmp_path, NAME, OTHER)
    imports = lint_imports(tmp_path, config, env)
    assert_ok(imports)
    assert "Contracts: 7 kept, 0 broken." in imports.stdout  # 2 per service, A9, A10, testing
    assert "Services never import each other (A9) KEPT" in imports.stdout
    assert_ok(run(BIN / "sb-checks", "run", "--root", tmp_path))

    # The A9 contract from OTHER's REGISTER.md bites: a cross-service import breaks it.
    cross = services[0] / "src" / NAME / "interface" / "peer.py"
    cross.write_text(f"import {OTHER}.bootstrap\n")
    broken = lint_imports(tmp_path, config, env)
    assert broken.returncode == 1
    assert "Services never import each other (A9) BROKEN" in broken.stdout


@pytest.mark.integration
def test_use_case_renders_a_red_stub(tmp_path: Path) -> None:
    service = render_service(tmp_path)
    render_use_case(service, "close_account")

    use_case = service / "src" / NAME / "application" / "use_cases" / "close_account.py"
    test = service / "tests" / "unit" / "use_cases" / "test_close_account.py"
    assert "R1: <state the first business rule>" in use_case.read_text()
    assert "class CloseAccount:" in use_case.read_text()
    assert "def test_R1_" in test.read_text()

    result = pytest_in(tmp_path, test, env=env_for(tmp_path, NAME))
    assert result.returncode == 1, result.stdout  # RED by design (T1): tests ran and failed
    assert "NotImplementedError" in result.stdout
    # The stub itself passes the machines, also at the longest names: only its test is red.
    render_use_case(render_service(tmp_path, OTHER), LONG_USE_CASE)
    assert_ok(ruff(tmp_path, "check", "services"))
    assert_ok(ruff(tmp_path, "format", "--check", "services"))
    config = pyright_config(tmp_path, NAME, OTHER)
    assert_ok(run(BIN / "pyright", "-p", config, env=env_for(tmp_path, NAME, OTHER)))
    assert_ok(run(BIN / "sb-checks", "run", "--root", tmp_path))


@pytest.mark.parametrize("name", ["Bad-Name", "x" * 33])
def test_the_use_case_template_refuses_bad_names(tmp_path: Path, name: str) -> None:
    service = render_service(tmp_path)
    with pytest.raises(ValueError, match="name"):
        render_use_case(service, name)
    assert not (service / "tests" / "unit" / "use_cases" / f"test_{name}.py").exists()


BAD_SERVICE_NAMES = [
    "infra",  # compose profiles and make names
    "core",
    "init",
    "tools",
    "tests",  # would shadow every service's tests package
    "class",  # Python keywords
    "match",
    "json",  # standard-library modules
    "asyncio",
    "sb_payments",  # reserved for platform libraries
    "Bad-Name",
    "1svc",
    "x" * 25,
]


@pytest.mark.parametrize("name", BAD_SERVICE_NAMES)
def test_the_template_refuses_bad_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        run_copy(str(SERVICE_TEMPLATE), tmp_path / "x", data={"name": name}, defaults=True)
    assert not (tmp_path / "x").exists()


def test_the_template_refuses_an_existing_member_or_service(tmp_path: Path) -> None:
    for data in ({"taken": "acme_lib other"}, {"peers": "ledger acme_lib"}):
        with pytest.raises(ValueError, match="name"):
            run_copy(
                str(SERVICE_TEMPLATE),
                tmp_path / "x",
                data={"name": "acme_lib", **data},
                defaults=True,
            )
    assert not (tmp_path / "x").exists()


def test_the_reserved_names_cover_this_python() -> None:
    """copier.yml cannot import Python, so it carries the list; it must cover every keyword and
    standard-library module of the running interpreter (regenerate it on a Python upgrade)."""
    config = yaml.safe_load((SERVICE_TEMPLATE / "copier.yml").read_text())
    reserved = set(config["reserved"]["default"])
    expected = {*keyword.kwlist, *keyword.softkwlist, *sys.stdlib_module_names}
    expected = {n for n in expected if re.fullmatch(r"[a-z][a-z0-9_]*", n)}
    assert expected - reserved == set()
    assert {"infra", "core", "init", "tools", "tests"} <= reserved


@pytest.mark.parametrize(
    ("peers", "exists", "expected"),
    [
        ("", False, "first service"),
        ("ledger", False, "[importlinter:contract:services-independent]"),
        ("ledger other", True, "add `demo_svc` to `modules` of `services-independent`"),
    ],
    ids=["first", "second", "third"],
)
def test_register_renders_the_a9_independence_snippet(
    tmp_path: Path, peers: str, exists: bool, expected: str
) -> None:
    service = render_service(tmp_path, peers=peers, independence_contract=exists)
    a9 = (service / "REGISTER.md").read_text().split("### Services never import services", 1)[1]
    a9 = a9.split("\n### ", 1)[0]
    assert expected in a9
    if peers and not exists:
        [block] = re.findall(r"```ini\n(.*?)```", a9, flags=re.DOTALL)
        assert block.split("modules =", 1)[1].split() == [*peers.split(), NAME]


def test_the_ledger_render_matches_the_ledger(tmp_path: Path) -> None:
    """Drift guard: rendered as `ledger`, the shared plumbing is the ledger's own code.

    Python files are compared as ASTs with docstrings removed, which ignores comments, blank
    lines and line wrapping (the template wraps name-bearing lines so every name fits in 100
    columns) and nothing else; the Dockerfile is compared without comments and blank lines.
    bootstrap.py, the fakes and the use cases are not compared: they hold the ledger's account
    code (the known difference)."""
    rendered = render_service(tmp_path, "ledger")
    ledger = REPO / "services" / "ledger"
    for rel in (
        "src/ledger/infrastructure/settings.py",
        "src/ledger/main.py",
        "src/ledger/migrate.py",
        "tests/conftest.py",
    ):
        assert code_of(rendered / rel) == code_of(ledger / rel), rel
    assert instructions(rendered / "Dockerfile") == instructions(ledger / "Dockerfile")


def code_of(path: Path) -> str:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
    return ast.dump(tree)


def instructions(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("new-service", "NAME=infra"), "reserved"),
        (("new-service", "NAME=Bad-Name"), "must match"),
        (("new-service", "NAME=ledger"), "already exists"),
        (("new-service", "NAME=core"), "reserved"),
        (("new-service", "NAME=tools"), "reserved"),
        (("new-service", "NAME=tests"), "reserved"),
        (("new-service", "NAME=class"), "Python keyword or standard-library module"),
        (("new-service", "NAME=json"), "Python keyword or standard-library module"),
        (("new-service", "NAME=sb_kernel"), "already a workspace member"),
        (("new-service", "NAME=sb_payments"), "reserved for platform libraries"),
        (("new-service", "NAME=x;touch_pwned"), "must match"),
        (("new-service",), "usage"),
        (("new-use-case", "SVC=ledger", "NAME=Bad-Name"), "must match"),
        (("new-use-case", "SVC=ledger", "NAME=open_account"), "already exists"),
        (("new-use-case", "SVC=no_such_svc", "NAME=close_account"), "no service"),
        (("new-use-case", "SVC=ledger"), "usage"),
    ],
    ids=[
        "reserved",
        "bad-service-name",
        "existing-service",
        "profile-core",
        "profile-tools",
        "tests",
        "keyword",
        "stdlib",
        "existing-member",
        "sb-prefix",
        "shell-metacharacters",
        "no-service-name",
        "bad-use-case-name",
        "existing-use-case",
        "unknown-service",
        "no-use-case-name",
    ],
)
def test_make_targets_refuse_bad_names(args: tuple[str, ...], message: str) -> None:
    before = run("git", "status", "--porcelain").stdout
    result = make(*args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert message in result.stdout + result.stderr
    assert run("git", "status", "--porcelain").stdout == before


def test_the_dockerfile_syntax_frontend_is_pinned_by_digest(tmp_path: Path) -> None:
    """The BuildKit frontend runs with the build's privileges: pin it like the base images."""
    pinned = re.compile(r"# syntax=docker/dockerfile:1\.7-labs@sha256:[0-9a-f]{64}")
    rendered = render_service(tmp_path) / "Dockerfile"
    for dockerfile in (REPO / "services" / "ledger" / "Dockerfile", rendered):
        first = dockerfile.read_text().splitlines()[0]
        assert pinned.fullmatch(first), f"{dockerfile}: {first}"
