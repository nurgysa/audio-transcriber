"""Tests for tasks.linear_client. HTTP is mocked via unittest.mock."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from tasks.linear_client import LinearClient, LinearError


# ── construction ──────────────────────────────────────────────────────


def test_client_rejects_empty_key():
    with pytest.raises(LinearError, match="ключ не задан"):
        LinearClient("")
    with pytest.raises(LinearError):
        LinearClient("   ")


def test_authorization_header_has_no_bearer_prefix():
    """Linear quirk — raw key, no 'Bearer'."""
    c = LinearClient("lin_api_test")
    assert c._session.headers["Authorization"] == "lin_api_test"


# ── validate_key ──────────────────────────────────────────────────────


def test_validate_key_returns_viewer_on_200():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "data": {"viewer": {"id": "u-1", "name": "Айдар", "email": "a@x.com"}}
    }
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake) as mock_post:
        v = c.validate_key()
    mock_post.assert_called_once()
    assert v == {"id": "u-1", "name": "Айдар", "email": "a@x.com"}


def test_validate_key_raises_on_graphql_error():
    """Linear returns 200 with 'errors' array on auth failure."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "errors": [{"message": "Authentication failed"}],
    }
    c = LinearClient("lin_api_bad")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="Authentication"):
            c.validate_key()


def test_validate_key_raises_on_http_500():
    fake = MagicMock()
    fake.status_code = 500
    fake.text = "Internal server error"
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="500"):
            c.validate_key()


# ── _graphql JSONDecodeError fix (review carry-over from Task 8) ──


def test_graphql_raises_LinearError_on_malformed_json_body():
    """200 with non-JSON body must surface as LinearError, not raw ValueError."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.side_effect = ValueError("Expecting value: line 1 column 1")
    fake.text = "<html>Service unavailable</html>"
    c = LinearClient("lin_api_test")
    with patch.object(c._session, "post", return_value=fake):
        with pytest.raises(LinearError, match="не-JSON"):
            c.validate_key()
