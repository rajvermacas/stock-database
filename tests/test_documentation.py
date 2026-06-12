from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "command",
    [
        "stock-data --config config/stock-data.toml update-all",
        "stock-data --config config/stock-data.toml update-symbol RELIANCE.NS",
    ],
)
def test_commands_document_contains_supported_commands(command: str) -> None:
    assert command in Path("COMMANDS.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "required",
    [
        "Python 3.12",
        "COMMANDS.md",
        "adjusted OHLCV",
        "initial_start_date",
        "full history",
        "Yahoo-provided volume",
        "Asia/Kolkata",
        "Parquet",
        "prices/<interval>/<symbol>.parquet",
        "indicators/<interval>/<symbol>.parquet",
        "full 365-calendar-day history",
        "TA-Lib",
        "1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo",
    ],
)
def test_readme_documents_required_behavior(required: str) -> None:
    assert required in Path("README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "forbidden",
    ["raw, unadjusted", "--start-date", "--end-date", "strictly after"],
)
def test_user_docs_do_not_describe_removed_behavior(forbidden: str) -> None:
    text = Path("README.md").read_text() + Path("COMMANDS.md").read_text()
    assert forbidden not in text


def test_similarity_skill_documents_required_contract() -> None:
    text = Path(".agents/skills/find-similar-stock-setups/SKILL.md").read_text()
    for required in [
        "same stock",
        "10-day",
        "non-overlapping",
        "adjusted",
        "combined distance",
        "subgroup",
        "not a probability",
        "find_similar_setups.py",
    ]:
        assert required in text


def test_chart_structure_skill_documents_required_contract() -> None:
    text = Path(".agents/skills/analyze-chart-structure/SKILL.md").read_text()
    for required in [
        "talk-to-stock-data",
        "generic structure",
        "developing",
        "confirmed",
        "invalidated",
        "explicitly requests",
        "analyze_structure.py",
        "confidence is not probability",
    ]:
        assert required in text
