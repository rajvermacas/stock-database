from __future__ import annotations

from scripts.kite import login as lg


def test_login_happy_path(mocker):
    mocker.patch.object(lg, "configure_logging")
    mocker.patch.object(
        lg, "load_credentials",
        return_value=mocker.Mock(api_key="k", api_secret="s"),
    )
    mocker.patch.object(lg, "build_login_url", return_value="http://login")
    mocker.patch.object(lg, "generate_access_token", return_value="AT")
    write = mocker.patch.object(lg, "write_access_token")
    assert lg.main(["--request-token", "rt"]) == 0
    write.assert_called_once_with("AT")


def test_login_missing_credentials_returns_2(mocker):
    from scripts.kite.credentials import KiteCredentialError

    mocker.patch.object(lg, "configure_logging")
    mocker.patch.object(
        lg, "load_credentials", side_effect=KiteCredentialError("no creds")
    )
    assert lg.main(["--request-token", "rt"]) == 2
