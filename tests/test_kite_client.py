from __future__ import annotations

import pytest
from kiteconnect.exceptions import TokenException

from scripts.kite import client
from scripts.kite.client import KiteAuthError, build_client, verify_token


def test_build_client_sets_token(mocker):
    mocker.patch.object(
        client, "load_credentials", return_value=mocker.Mock(api_key="k")
    )
    mocker.patch.object(client, "read_access_token", return_value="AT")
    fake = mocker.Mock()
    mocker.patch.object(client, "KiteConnect", return_value=fake)
    result = build_client()
    assert result is fake
    fake.set_access_token.assert_called_once_with("AT")


def test_verify_token_ok(mocker):
    kite = mocker.Mock()
    kite.profile.return_value = {"user_id": "AB1234"}
    verify_token(kite)  # must not raise


def test_verify_token_expired(mocker):
    kite = mocker.Mock()
    kite.profile.side_effect = TokenException("bad token")
    with pytest.raises(KiteAuthError):
        verify_token(kite)
