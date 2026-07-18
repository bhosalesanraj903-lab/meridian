"""State store tests: local JSON backend directly, DynamoDB backend via moto."""
import boto3
import pytest
from moto import mock_aws

from meridian.state import DynamoDbState, LocalJsonState


class TestLocalJsonState:
    def test_ofac_swap_and_noop(self, tmp_path):
        store = LocalJsonState(str(tmp_path / "state.json"))
        assert store.get_ofac_state() == {}
        assert store.swap_ofac_hash({"last_sha256": "aaa"}) is True
        assert store.get_ofac_state()["last_sha256"] == "aaa"
        assert store.swap_ofac_hash({"last_sha256": "aaa"}) is False
        assert store.swap_ofac_hash({"last_sha256": "bbb"}) is True

    def test_batch_ledger(self, tmp_path):
        store = LocalJsonState(str(tmp_path / "state.json"))
        assert store.claim_batch("b1", {"at": "t"}) is True
        assert store.claim_batch("b1", {"at": "t"}) is False
        store.release_batch("b1")
        assert store.claim_batch("b1", {"at": "t"}) is True


@pytest.fixture
def dynamo_store():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="meridian-state",
            KeySchema=[{"AttributeName": "entity", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "entity", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoDbState("meridian-state", "us-east-1")


class TestDynamoDbState:
    def test_ofac_swap_and_noop(self, dynamo_store):
        assert dynamo_store.get_ofac_state() == {}
        assert dynamo_store.swap_ofac_hash({"last_sha256": "aaa"}) is True
        assert dynamo_store.get_ofac_state()["last_sha256"] == "aaa"
        assert dynamo_store.swap_ofac_hash({"last_sha256": "aaa"}) is False
        assert dynamo_store.swap_ofac_hash({"last_sha256": "bbb"}) is True

    def test_batch_ledger(self, dynamo_store):
        assert dynamo_store.claim_batch("b1", {"at": "t"}) is True
        assert dynamo_store.claim_batch("b1", {"at": "t"}) is False
        dynamo_store.release_batch("b1")
        assert dynamo_store.claim_batch("b1", {"at": "t"}) is True
