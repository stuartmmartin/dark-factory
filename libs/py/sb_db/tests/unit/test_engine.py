from sb_db.engine import create_engine


def test_engine_hides_bound_parameters_from_logs_and_errors() -> None:
    engine = create_engine("postgresql+asyncpg://u:p@localhost/x")
    assert engine.sync_engine.hide_parameters is True
