# tests/test_linear_client_list_comments.py
from tasks.linear_client import LinearClient


def test_list_comments_returns_bodies(monkeypatch):
    c = LinearClient(api_key="k")
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: {
        "issue": {"comments": {"nodes": [{"body": "hello"}, {"body": "world"}]}}
    })
    assert c.list_comments("uuid-1") == ["hello", "world"]


def test_list_comments_empty(monkeypatch):
    c = LinearClient(api_key="k")
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: {"issue": {"comments": {"nodes": []}}})
    assert c.list_comments("uuid-1") == []
