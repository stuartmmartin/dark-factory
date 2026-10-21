from uuid import UUID

from ledger.domain.events import AccountOpened


def test_account_opened_topic_key_and_payload() -> None:
    event = AccountOpened(account_id=UUID(int=5), currency="USD")
    assert AccountOpened.topic() == "ledger.account.opened.v1"
    assert event.event_key() == str(UUID(int=5))
    assert event.model_dump(mode="json") == {"account_id": str(UUID(int=5)), "currency": "USD"}
