from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "command",
    [
        "stock-data --config config/stock-data.toml update-all",
        "stock-data --config config/stock-data.toml update-symbol RELIANCE.NS",
        "--start-date 2026-05-01 --end-date 2026-05-31",
    ],
)
def test_commands_document_contains_supported_commands(command: str) -> None:
    assert command in Path("COMMANDS.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "required",
    [
        "Python 3.12",
        "COMMANDS.md",
        "strictly after",
        "Asia/Kolkata",
        "Parquet",
        "prices/<interval>/<symbol>.parquet",
        "1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo",
    ],
)
def test_readme_documents_required_behavior(required: str) -> None:
    assert required in Path("README.md").read_text(encoding="utf-8")
