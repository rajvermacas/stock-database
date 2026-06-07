import stock_data


def test_package_exposes_version() -> None:
    assert stock_data.__version__ == "0.1.0"

