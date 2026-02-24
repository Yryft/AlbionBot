from datetime import datetime
from zoneinfo import ZoneInfo

TZ_PARIS = ZoneInfo("Europe/Paris")

def parse_dt_paris(dt_str: str) -> int:
    dt = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M")
    dt = dt.replace(tzinfo=TZ_PARIS)
    return int(dt.timestamp())
