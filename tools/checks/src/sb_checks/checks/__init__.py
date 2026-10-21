"""Registry of every convention check run by ``sb-checks run``."""

from sb_checks.checks.banned_module_names import BannedModuleNamesCheck
from sb_checks.checks.httpx_timeout import HttpxTimeoutCheck
from sb_checks.checks.no_env_read import NoEnvReadCheck
from sb_checks.checks.no_float import NoFloatCheck
from sb_checks.checks.no_member_tool_config import NoMemberToolConfigCheck
from sb_checks.checks.no_mock_in_unit import NoMockInUnitCheck
from sb_checks.checks.no_naive_now import NoNaiveNowCheck
from sb_checks.checks.use_case_rules import UseCaseRulesCheck
from sb_checks.core import AnyCheck

ALL_CHECKS: tuple[AnyCheck, ...] = (
    NoFloatCheck(),
    NoNaiveNowCheck(),
    NoEnvReadCheck(),
    NoMockInUnitCheck(),
    BannedModuleNamesCheck(),
    HttpxTimeoutCheck(),
    UseCaseRulesCheck(),
    NoMemberToolConfigCheck(),
)
