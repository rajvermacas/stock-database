from __future__ import annotations

import pytest

from scripts.kite import credentials
from scripts.kite.credentials import (
    KiteCredentialError,
    load_credentials,
    read_access_token,
    write_access_token,
)


def test_load_credentials_ok(tmp_path, monkeypatch):
    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('api_key = "k"\napi_secret = "s"\n', encoding="utf-8")
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", cred_file)
    creds = load_credentials()
    assert creds.api_key == "k"
    assert creds.api_secret == "s"


def test_load_credentials_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", tmp_path / "nope.toml")
    with pytest.raises(KiteCredentialError):
        load_credentials()


def test_load_credentials_missing_key(tmp_path, monkeypatch):
    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('api_key = "k"\n', encoding="utf-8")
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", cred_file)
    with pytest.raises(KiteCredentialError):
        load_credentials()


def test_token_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "SECRETS_DIR", tmp_path)
    monkeypatch.setattr(credentials, "TOKEN_FILE", tmp_path / "access_token.json")
    write_access_token("tok123")
    assert read_access_token() == "tok123"


def test_read_token_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "TOKEN_FILE", tmp_path / "absent.json")
    with pytest.raises(KiteCredentialError):
        read_access_token()
