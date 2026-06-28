from __future__ import annotations

import pytest

from scripts.kite import auth
from scripts.kite.auth import extract_request_token, generate_access_token


def test_extract_bare_token():
    assert extract_request_token("  abc123 ") == "abc123"


def test_extract_from_url():
    url = "https://127.0.0.1/?request_token=xyz789&action=login&status=success"
    assert extract_request_token(url) == "xyz789"


def test_extract_empty_raises():
    with pytest.raises(ValueError):
        extract_request_token("   ")


def test_generate_access_token(mocker):
    fake = mocker.Mock()
    fake.generate_session.return_value = {"access_token": "AT"}
    mocker.patch.object(auth, "KiteConnect", return_value=fake)
    token = generate_access_token("k", "s", "rt")
    assert token == "AT"
    fake.generate_session.assert_called_once_with("rt", api_secret="s")
