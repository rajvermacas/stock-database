from __future__ import annotations

from scripts.kite import login as lg
from scripts.kite import place_orders as po
from scripts.kite.client import KiteAuthError
from scripts.kite.placement import OrderResult


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


def _patch_setup(mocker):
    mocker.patch.object(po, "configure_logging")
    mocker.patch.object(po, "build_client", return_value=mocker.Mock())
    mocker.patch.object(po, "verify_token")
    mocker.patch.object(po, "load_orders", return_value=["o1"])


def test_place_orders_all_ok(mocker, tmp_path):
    _patch_setup(mocker)
    mocker.patch.object(
        po, "run_batch",
        return_value=[OrderResult(1, "regular", "INFY", "BUY", 1, True, "OID1")],
    )
    assert po.main(["--orders", str(tmp_path / "o.json")]) == 0


def test_place_orders_partial_failure(mocker, tmp_path):
    _patch_setup(mocker)
    mocker.patch.object(
        po, "run_batch",
        return_value=[OrderResult(1, "regular", "INFY", "BUY", 1, False, "err")],
    )
    assert po.main(["--orders", str(tmp_path / "o.json")]) == 1


def test_place_orders_setup_failure(mocker, tmp_path):
    mocker.patch.object(po, "configure_logging")
    mocker.patch.object(po, "build_client", side_effect=KiteAuthError("no token"))
    assert po.main(["--orders", str(tmp_path / "o.json")]) == 2
