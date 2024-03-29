import datetime

from typing import Dict

from ..test_support._datetime import fromisoformat_z
from .expected_data import ExpectedData


class ExpectedUser:
    def __init__(self, user_dict: Dict):
        self._data = user_dict

    @property
    def uuid(self) -> str:
        return self._data["uuid"]

    @property
    def created_at(self) -> datetime.datetime:
        created_at = self._data["createdAt"]
        return fromisoformat_z(created_at)

    @property
    def updated_at(self) -> datetime.datetime:
        updated_at = self._data["updatedAt"]
        return fromisoformat_z(updated_at)

    @property
    def last_auth_at(self) -> datetime.datetime:
        updated_at = self._data["lastAuthAt"]
        return fromisoformat_z(updated_at)

    @property
    def email(self) -> str:
        return self._data["email"]

    @property
    def first_name(self) -> str:
        return self._data["firstName"]

    @property
    def last_name(self) -> str:
        return self._data["lastName"]

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def returncode(self) -> int:
        return self._data["returncode"]


class ExpectedUserData:
    def __init__(self):
        expected_data = ExpectedData()
        user_data: Dict = expected_data.user_data
        self._data: Dict = user_data

    def data_for_user(self, user_identifier: str):
        user_dict = self._data[user_identifier]
        user = ExpectedUser(user_dict)
        return user
