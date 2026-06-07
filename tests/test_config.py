from pathlib import Path

import pytest

from stock_data.config import ConfigError, load_config

VALID = """
[paths]
data_dir = "../market-data"
symbols_file = "../market-data/metadata/symbols.csv"
[download]
initial_start_date = "2000-01-01"
[yahoo]
interval = "1d"
batch_size = 50
timeout_seconds = 30
threads = true
"""


def write_config(tmp_path: Path, text: str = VALID) -> Path:
    path = tmp_path / "config" / "stock-data.toml"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_resolves_paths(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    config = load_config(path)
    assert config.paths.data_dir == (path.parent / "../market-data").resolve()
    assert config.paths.prices_dir == config.paths.data_dir / "prices"
    assert config.download.initial_start_date.isoformat() == "2000-01-01"


@pytest.mark.parametrize(
    "text",
    [
        VALID.replace("batch_size = 50\n", ""),
        VALID.replace('interval = "1d"', 'interval = "1h"'),
        VALID.replace("batch_size = 50", "batch_size = 0"),
        VALID + "\nunknown = true\n",
    ],
)
def test_load_config_rejects_invalid_values(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, text))

