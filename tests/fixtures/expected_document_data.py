from typing import Dict

from .expected_data import ExpectedData


class ExpectedDocument:

    def __init__(self, document_dict: Dict):
        self._data = document_dict

    @property
    def digest(self) -> str:
        return self._data.get("digest", None)

    @property
    def size(self) -> int:
        return self._data.get("size", None)

    @property
    def filename(self) -> str:
        return self._data.get("filename", None)

    @property
    def returncode(self) -> int:
        return self._data["returncode"]


class ExpectedDocumentData:
    def __init__(self):
        expected_data = ExpectedData()
        item_data: Dict = expected_data.document_data
        self._data: Dict = item_data

    def data_for_document(self, document_identifier):
        document_dict = self._data[document_identifier]
        document_data = ExpectedDocument(document_dict)
        return document_data
