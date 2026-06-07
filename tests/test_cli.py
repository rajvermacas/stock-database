from pathlib import Path

from typer.testing import CliRunner

from stock_data.cli import app
from stock_data.service import SymbolResult, SymbolStatus, UpdateSummary

runner = CliRunner()


def test_update_symbol_prints_summary(mocker, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    summary = UpdateSummary((SymbolResult("TCS.NS", SymbolStatus.SUCCESS),))
    mocker.patch("stock_data.cli.load_config")
    mocker.patch("stock_data.cli.configure_logging")
    mocker.patch("stock_data.cli._run", return_value=summary)
    result = runner.invoke(app, ["--config", str(config), "update-symbol", "TCS.NS"])
    assert result.exit_code == 0
    assert "Successful: 1" in result.stdout


def test_update_symbol_returns_one_on_partial_failure(mocker, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    summary = UpdateSummary((SymbolResult("TCS.NS", SymbolStatus.FAILED, error="bad"),))
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
