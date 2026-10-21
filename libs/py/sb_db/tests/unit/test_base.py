from sb_db.base import NAMING_CONVENTION, make_base


def test_make_base_gives_each_service_fresh_metadata_with_naming_convention() -> None:
    first, second = make_base(), make_base()
    assert first.metadata is not second.metadata
    assert first.metadata.naming_convention == NAMING_CONVENTION
