from pathlib import Path

from typer.testing import CliRunner

from stock_data.cli import app
from stock_data.config import AppConfig
from stock_data.service import SymbolResult, SymbolStatus, UpdateSummary

runner = CliRunner()


def test_update_symbol_prints_summary(mocker, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    summary = UpdateSummary((SymbolResult("TCS.NS", SymbolStatus.SUCCESS, 1, 1, None),))
    mocker.patch("stock_data.cli.load_config")
    mocker.patch("stock_data.cli.configure_logging")
    mocker.patch("stock_data.cli._run", return_value=summary)
    result = runner.invoke(app, ["--config", str(config), "update-symbol", "TCS.NS"])
    assert result.exit_code == 0
    assert "Successful: 1" in result.stdout


def test_update_symbol_returns_one_on_partial_failure(mocker, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    summary = UpdateSummary((SymbolResult("TCS.NS", SymbolStatus.FAILED, 0, 0, "bad"),))
    mocker.patch("stock_data.cli.load_config")
    mocker.patch("stock_data.cli.configure_logging")
    mocker.patch("stock_data.cli._run", return_value=summary)
    result = runner.invoke(app, ["--config", str(config), "update-symbol", "TCS.NS"])
    assert result.exit_code == 1
    assert "Failed: 1" in result.stdout


def test_unpaired_range_returns_validation_exit(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    result = runner.invoke(
        app, ["--config", str(config), "update-all", "--start-date", "2026-06-01"]
    )
    assert result.exit_code == 2
    assert "must be supplied together" in result.output


def test_run_uses_configured_interval(mocker, tmp_path: Path) -> None:
    from stock_data.cli import _run

    config = AppConfig.model_validate(
        {
            "paths": {"data_dir": tmp_path, "symbols_file": tmp_path / "symbols.csv"},
            "download": {"initial_start_date": "2026-01-01"},
            "yahoo": {
                "interval": "30m",
                "batch_size": 2,
                "timeout_seconds": 30,
                "threads": False,
            },
        }
    )
    store = mocker.patch("stock_data.cli.PriceStore")
    update = mocker.patch("stock_data.cli.UpdateService").return_value.update
    update.return_value = UpdateSummary(())
    _run(config, ["TCS.NS"], None, None)
    assert store.call_args.args[1].name == "30m"
