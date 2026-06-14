import json
from datetime import datetime

from stock_data.intervals import IST
from stock_data.pullback.models import ScreenResult
from stock_data.pullback.report import render_json, render_markdown


def test_empty_report_discloses_fixed_stop_and_counts() -> None:
    result = ScreenResult(datetime(2026, 1, 1, tzinfo=IST), (), (), (), ())
    text = render_markdown(result)
    assert "fixed 3% stop" in text
    assert "No stock-specific setup beat abstention." in text
    assert "Abstained: 0" in text
    assert json.loads(render_json(result))["ranked"] == []
