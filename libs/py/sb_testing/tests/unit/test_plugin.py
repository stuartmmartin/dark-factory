import structlog


def test_structlog_state_leaks_are_reset_between_tests_part_one() -> None:
    structlog.configure(processors=[])
    structlog.contextvars.bind_contextvars(leak="yes")


def test_structlog_state_leaks_are_reset_between_tests_part_two() -> None:
    assert structlog.contextvars.get_contextvars() == {}
    assert structlog.is_configured() is False
