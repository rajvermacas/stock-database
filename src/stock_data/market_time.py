from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_DATA_READY = time(16, 0)


def latest_completed_date(now: datetime) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    ist_now = now.astimezone(IST)
    if ist_now.time() >= MARKET_DATA_READY:
        return ist_now.date()
    return ist_now.date() - timedelta(days=1)
