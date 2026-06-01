# tests/test_trello_backend_dedup.py
from tasks.backends.base import ExistingItem
from tasks.backends.trello import TrelloBackend


class _FakeClient:
    def list_open_cards(self, list_id):
        return [
            {"id": "card-1", "name": "Изучить СУП", "desc": "d1",
             "url": "http://c/1", "idShort": 5, "shortLink": "abc"},
            {"id": "card-2", "name": "Без idShort", "desc": "",
             "url": "", "idShort": None, "shortLink": "shortX"},
        ]

    def list_card_comments(self, card_id):
        return ["x <!-- audiotx-dedup:sig1 -->"]


def test_list_existing_maps_cards():
    b = TrelloBackend(_FakeClient())
    items = b.list_existing("list-1")
    assert items[0] == ExistingItem(
        title="Изучить СУП", ref="card-1", identifier="#5",
        url="http://c/1", description="d1",
    )
    # idShort missing → fall back to shortLink
    assert items[1].identifier == "shortX"


def test_comment_exists():
    b = TrelloBackend(_FakeClient())
    assert b.comment_exists("card-1", "<!-- audiotx-dedup:sig1 -->") is True
    assert b.comment_exists("card-1", "<!-- audiotx-dedup:other -->") is False


def test_idshort_zero_uses_hash_not_shortlink():
    class _ZeroClient:
        def list_open_cards(self, list_id):
            return [{"id": "card-0", "name": "Zero", "desc": "",
                     "url": "", "idShort": 0, "shortLink": "sl0"}]

        def list_card_comments(self, card_id):
            return []

    b = TrelloBackend(_ZeroClient())
    items = b.list_existing("list-1")
    # idShort 0 is falsy but not None → must render "#0", NOT the shortLink
    assert items[0].identifier == "#0"
