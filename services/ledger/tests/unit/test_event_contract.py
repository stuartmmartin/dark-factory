"""The AccountOpened payload matches its committed JSON Schema contract (kafka-event skill)."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import jsonschema
import pytest

from ledger.domain.events import AccountOpened

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts" / "events"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads((CONTRACTS / f"{AccountOpened.topic()}.json").read_text())


def test_account_opened_payload_validates_against_its_contract(schema: dict[str, Any]) -> None:
    payload = AccountOpened(account_id=UUID(int=7), currency="USD").model_dump(mode="json")
    jsonschema.validate(payload, schema)


@pytest.mark.parametrize(
    "payload",
    [
        {"account_id": str(UUID(int=7)), "currency": "USD", "name": "Cash"},
        {"account_id": str(UUID(int=7)), "currency": "usd"},
        {"account_id": str(UUID(int=7))},
        {"currency": "USD"},
        {"account_id": "not-a-uuid", "currency": "USD"},
    ],
    ids=["extra-field", "lowercase-currency", "no-currency", "no-account-id", "non-uuid-id"],
)
def test_invalid_payloads_fail_the_contract(
    schema: dict[str, Any], payload: dict[str, Any]
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_the_contract_is_a_draft_2020_12_schema(schema: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
