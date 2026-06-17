from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from stock_data.intervals import get_interval


class ConfigError(ValueError):
    """Raised when application configuration is invalid."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsConfig(StrictModel):
    data_dir: Path
    symbols_file: Path

    @property
    def prices_dir(self) -> Path:
        return self.data_dir / "prices"

    @property
    def indicators_dir(self) -> Path:
        return self.data_dir / "indicators"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


class DownloadConfig(StrictModel):
    initial_start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_end_date(self) -> Self:
        if self.end_date is not None and self.end_date < self.initial_start_date:
            raise ValueError(
                f"end_date {self.end_date} is before "
                f"initial_start_date {self.initial_start_date}"
            )
        return self


class YahooConfig(StrictModel):
    interval: str
    batch_size: int = Field(gt=0)
    timeout_seconds: int = Field(gt=0)
    threads: bool

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, value: str) -> str:
        get_interval(value)
        return value


class IndicatorsConfig(StrictModel):
    enabled: bool


class AppConfig(StrictModel):
    paths: PathsConfig
    download: DownloadConfig
    yahoo: YahooConfig
    indicators: IndicatorsConfig

    def resolve_relative_paths(self, base: Path) -> Self:
        paths = self.paths.model_copy(
            update={
                "data_dir": _resolve(base, self.paths.data_dir),
                "symbols_file": _resolve(base, self.paths.symbols_file),
            }
        )
        return self.model_copy(update={"paths": paths})


def _resolve(base: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_config(path: Path) -> AppConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(raw).resolve_relative_paths(path.parent)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ConfigError(f"Invalid configuration {path}: {exc}") from exc
