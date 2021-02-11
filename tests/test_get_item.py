from typing import Dict
from pyonepassword import OP
from tests.fixtures.expected_data import ExpectedData


def _lookup_item_data(data: ExpectedData, item_id: str) -> Dict:
    item = data.lookup_item(item_id)
    return item


def test_get_item_01(signed_in_op: OP, expected_data):

    item_name = "Example Login 1"
    vault = "Test Data"
    expected = _lookup_item_data(expected_data, item_name)
    result = signed_in_op.get_item(item_name, vault=vault)
    assert result.username == expected["username"]
    assert result.password == expected["password"]

def test_get_item_02(signed_in_op: OP, expected_data):

    item_uuid = "nok7367v4vbsfgg2fczwu4ei44"
    expected = _lookup_item_data(expected_data, item_uuid)
    result = signed_in_op.get_item(item_uuid)
    assert result.username == expected["username"]
    assert result.password == expected["password"]