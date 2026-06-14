from pathlib import Path

from typer.testing import CliRunner

from stock_data.pullback.cli import app

runner = CliRunner()


def test_screen_requires_interval_and_output(tmp_path: Path) -> None:
    result = runner.invoke(app, ["screen", "--prices-root", str(tmp_path)])
    assert result.exit_code == 2
